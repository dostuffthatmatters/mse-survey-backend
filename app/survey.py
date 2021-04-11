import os
import asyncio

from fastapi import HTTPException
from starlette.responses import RedirectResponse
from pymongo.errors import DuplicateKeyError
from cachetools import LRUCache

from app.validation import SubmissionValidator, ConfigurationValidator
from app.aggregation import Alligator
from app.utils import combine, now
from app.cryptography import vtoken


# frontend url
FRONTEND_URL = os.getenv('FRONTEND_URL')


class SurveyManager:
    """The manager manages creating, updating and deleting surveys."""


    # TODO make distinction between frontend/backend configuration format
    # clearer, e.g. move exception handling into public functions and give
    # private functions only the finished configuration document as
    # argument.


    def __init__(self, database, letterbox, jwt_manager):
        """Initialize a survey manager instance."""
        self.database = database
        self.letterbox = letterbox
        self.cache = LRUCache(maxsize=256)
        self.validator = ConfigurationValidator.create()
        self.jwt_manager = jwt_manager

    def _update_cache(self, configuration):
        """Update survey object in the local cache."""
        survey_id = combine(
            configuration['username'],
            configuration['survey_name'],
        )
        self.cache[survey_id] = Survey(
            configuration,
            self.database,
            self.letterbox,
        )

    async def fetch(self, username, survey_name):
        """Return survey configuration corresponding to user/survey name."""
        survey = await self._fetch(username, survey_name)
        return {
            key: survey.configuration[key]
            for key
            in survey.configuration.keys()
            if key not in ['username']
        }

    async def create(
            self,
            username,
            survey_name,
            configuration,
            access_token,
        ):
        """Create a new survey configuration in the database and cache."""
        self.jwt_manager.authorize(username, access_token)
        await self._create(username, survey_name, configuration)

    async def update(
            self,
            username,
            survey_name,
            configuration,
            access_token,
        ):
        """Update a survey configuration in the database and cache."""
        self.jwt_manager.authorize(username, access_token)
        await self._update(username, survey_name, configuration)

    async def reset(self, username, survey_name, access_token):
        """Delete all submission data including the results of a survey."""
        self.jwt_manager.authorize(username, access_token)
        await self._reset(username, survey_name)

    async def delete(self, username, survey_name, access_token):
        """Delete the survey and all its data from the database and cache."""
        self.jwt_manager.authorize(username, access_token)
        await self._delete(username, survey_name)

    async def _fetch(self, username, survey_name):
        """Return the survey object corresponding to user and survey name."""
        survey_id = combine(username, survey_name)
        if survey_id not in self.cache:
            configuration = await self.database['configurations'].find_one(
                filter={'username': username, 'survey_name': survey_name},
                projection={'_id': False},
            )
            if configuration is None:
                raise HTTPException(404, 'survey not found')
            self._update_cache(configuration)
        return self.cache[survey_id]

    async def _create(self, username, survey_name, configuration):
        """Create a new survey configuration in the database and cache.

        The configuration includes the survey_name despite it already being
        specified in the route. We do this in order to enable changing the
        survey_name.

        """
        if survey_name != configuration['survey_name']:
            raise HTTPException(400, 'invalid configuration')
        if not self.validator.validate(configuration):
            raise HTTPException(400, 'invalid configuration')
        configuration['username'] = username
        try:
            await self.database['configurations'].insert_one(configuration)
            del configuration['_id']

            # TODO also delete the username from the configuration here?
            # like this the configuration in the survey is the same as
            # the one that is sent around in the routes

            self._update_cache(configuration)
        except DuplicateKeyError:
            raise HTTPException(400, 'survey exists')

    async def _update(self, username, survey_name, configuration):
        """Update a survey configuration in the database and cache.

        Survey updates are only possible if the survey has not yet started.
        This means that the only thing to update in the database is the
        configuration, as there are no existing submissions or results.

        """

        # TODO make update only possible if survey has not yet started

        if not self.validator.validate(configuration):
            raise HTTPException(400, 'invalid configuration')
        configuration['username'] = username
        result = await self.database['configurations'].replace_one(
            filter={'username': username, 'survey_name': survey_name},
            replacement=configuration,
        )
        if result.matched_count == 0:
            raise HTTPException(400, 'not an existing survey')

        assert '_id' not in configuration.keys()
        assert '_id' in configuration.keys()

        self._update_cache(configuration)

    async def _archive(self, username, survey_name):
        """Delete submission data of a survey, but keep the results."""
        survey_id = combine(username, survey_name)
        await self.database[f'surveys.{survey_id}.submissions'].drop()
        await self.database[f'surveys.{survey_id}.verified-submissions'].drop()

    async def _reset(self, username, survey_name):
        """Delete all submission data including the results of a survey."""
        survey_id = combine(username, survey_name)
        await self.database['results'].delete_one({'_id': survey_id})
        await self.database[f'surveys.{survey_id}.submissions'].drop()
        await self.database[f'surveys.{survey_id}.verified-submissions'].drop()

    async def _delete(self, username, survey_name):
        """Delete the survey and all its data from the database and cache."""
        await self.database['configurations'].delete_one(
            filter={'username': username, 'survey_name': survey_name},
        )
        survey_id = combine(username, survey_name)
        if survey_id in self.cache:
            del self.cache[survey_id]
        await self.database['results'].delete_one({'_id': survey_id})
        await self.database[f'surveys.{survey_id}.submissions'].drop()
        await self.database[f'surveys.{survey_id}.verified-submissions'].drop()


class Survey:
    """The survey class that all surveys instantiate."""

    def __init__(
            self,
            configuration,
            database,
            letterbox,
    ):
        """Create a survey from the given json configuration file."""
        self.configuration = configuration
        self.username = self.configuration['username']
        self.survey_name = self.configuration['survey_name']
        self.start = self.configuration['start']
        self.end = self.configuration['end']
        self.authentication = self.configuration['authentication']
        self.ei = Survey._get_email_field_index(self.configuration)
        self.validator = SubmissionValidator.create(self.configuration)
        self.letterbox = letterbox
        self.alligator = Alligator(self.configuration, database)
        self.submissions = database[
            f'surveys'
            f'.{combine(self.username, self.survey_name)}'
            f'.submissions'
        ]
        self.verified_submissions = database[
            f'surveys'
            f'.{combine(self.username, self.survey_name)}'
            f'.submissions.verified'
        ]
        self.results = None

    @staticmethod
    def _get_email_field_index(configuration):
        """Find the index of the email field in a survey configuration."""
        for index, field in enumerate(configuration['fields']):
            if field['type'] == 'email':
                return index
        return None

    async def submit(self, submission):
        """Save a user submission in the submissions collection."""
        submission_time = now()
        if submission_time < self.start:
            raise HTTPException(400, 'survey is not open yet')
        if submission_time >= self.end:
            raise HTTPException(400, 'survey is closed')
        if not self.validator.validate(submission):
            raise HTTPException(400, 'invalid submission')
        submission = {
            'submission_time': submission_time,
            'data': submission,
        }
        if self.authentication == 'open':
            await self.submissions.insert_one(submission)
        if self.authentication == 'email':
            submission['_id'] = vtoken()
            while True:
                try:
                    await self.submissions.insert_one(submission)
                    break
                except DuplicateKeyError:
                    submission['_id'] = vtoken()
            status = await self.letterbox.send_submission_verification_email(
                self.username,
                self.survey_name,
                self.configuration['title'],
                submission['data'][str(self.ei + 1)],
                submission['_id'],
            )
            if status != 200:
                raise HTTPException(500, 'email delivery failure')
        if self.authentication == 'invitation':
            raise HTTPException(501, 'not implemented')

    async def verify(self, verification_token):
        """Verify the user's email address and save submission as verified."""
        verification_time = now()
        if self.authentication != 'email':
            raise HTTPException(400, 'survey does not verify email addresses')
        if verification_time < self.start:
            raise HTTPException(400, 'survey is not open yet')
        if verification_time >= self.end:
            raise HTTPException(400, 'survey is closed')
        submission = await self.submissions.find_one(
            {'_id': verification_token},
        )
        if submission is None:
            raise HTTPException(401, 'invalid verification token')
        submission['verification_time'] = verification_time
        submission['_id'] = submission['data'][str(self.ei + 1)]
        await self.verified_submissions.find_one_and_replace(
            filter={'_id': submission['_id']},
            replacement=submission,
            upsert=True,
        )
        return RedirectResponse(
            f'{FRONTEND_URL}/{self.username}/{self.survey_name}/success'
        )

    async def aggregate(self):
        """Query the survey submissions and return aggregated results."""
        if now() < self.end:
            raise HTTPException(400, 'survey is not yet closed')
        self.results = self.results or await self.alligator.fetch()
        return self.results
