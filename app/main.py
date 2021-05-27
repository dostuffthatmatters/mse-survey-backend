import fastapi
import fastapi.middleware.cors
import pydantic

import app.account as ac
import app.survey as sv
import app.documentation as docs
import app.cryptography.access as access


# create fastapi app
app = fastapi.FastAPI(
    title='FastSurvey',
    version='0.3.0',
    docs_url='/documentation/swagger',
    redoc_url='/documentation/redoc',
)
# configure cross-origin resource sharing
app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
# instantiate survey manager
survey_manager = sv.SurveyManager()
# instantiate account manager
account_manager = ac.AccountManager(survey_manager)


################################################################################
# Pydantic Type Definitions
################################################################################


class AccountData(pydantic.BaseModel):
    username: str
    email_address: str
    password: str


class AuthenticationCredentials(pydantic.BaseModel):
    identifier: str
    password: str


class VerificationCredentials(pydantic.BaseModel):
    verification_token: str
    password: str


################################################################################
# Routes
################################################################################


@app.get(**docs.specifications['fetch_user'])
@access.authorize
async def fetch_user(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
    ):
    """Fetch the given user's account data."""
    return await account_manager.fetch(username)


@app.post(**docs.specifications['create_user'])
async def create_user(
        username: str = docs.arguments['username'],
        account_data: dict = docs.arguments['account_data'],
    ):
    """Create a new user based on the given account data."""
    await account_manager.create(username, account_data)


@app.put(**docs.specifications['update_user'])
@access.authorize
async def update_user(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        account_data: dict = docs.arguments['account_data'],
    ):
    """Update the given user's account data."""
    await account_manager.update(username, account_data)


@app.delete(**docs.specifications['delete_user'])
@access.authorize
async def delete_user(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
    ):
    """Delete the user and all their surveys from the database."""
    await account_manager.delete(username)


@app.get(**docs.specifications['fetch_surveys'])
@access.authorize
async def fetch_surveys(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        skip: int = docs.arguments['skip'],
        limit: int = docs.arguments['limit'],
    ):
    """Fetch the user's survey configurations sorted by the start date.

    As this is a protected route, configurations of surveys that are in
    draft mode **are** returned.

    """
    return await account_manager.fetch_configurations(username, skip, limit)


@app.get(**docs.specifications['fetch_survey'])
async def fetch_survey(
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
    ):
    """Fetch a survey configuration.

    As this is an unprotected route, configurations of surveys that are in
    draft mode **are not** returned.

    """
    return await survey_manager.fetch_configuration(username, survey_name)


@app.post(**docs.specifications['create_survey'])
@access.authorize
async def create_survey(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
        configuration: dict = docs.arguments['configuration'],
    ):
    """Create new survey with given configuration."""
    await survey_manager.create(username, survey_name, configuration)


@app.put(**docs.specifications['update_survey'])
@access.authorize
async def update_survey(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
        configuration: dict = docs.arguments['configuration'],
    ):
    """Update survey with given configuration."""
    await survey_manager.update(username, survey_name, configuration)


@app.delete(**docs.specifications['reset_survey'])
@access.authorize
async def reset_survey(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
    ):
    """Reset a survey by deleting all submission data including any results."""
    await survey_manager.reset(username, survey_name)


@app.delete(**docs.specifications['delete_survey'])
@access.authorize
async def delete_survey(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
    ):
    """Delete given survey including all its submissions and other data."""
    await survey_manager.delete(username, survey_name)


@app.post(**docs.specifications['create_submission'])
async def create_submission(
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
        submission: dict = docs.arguments['submission'],
    ):
    """Validate submission and store it under pending submissions."""
    survey = await survey_manager.fetch(username, survey_name)
    return await survey.submit(submission)


@app.get(**docs.specifications['verify_submission'])
async def verify_submission(
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
        verification_token: str = docs.arguments['verification_token'],
    ):
    """Verify user token and either fail or redirect to success page."""
    survey = await survey_manager.fetch(username, survey_name)
    return await survey.verify(verification_token)


@app.get(**docs.specifications['fetch_results'])
@access.authorize
async def fetch_results(
        access_token: str = docs.arguments['access_token'],
        username: str = docs.arguments['username'],
        survey_name: str = docs.arguments['survey_name'],
    ):
    """Fetch the results of the given survey."""
    survey = await survey_manager.fetch(username, survey_name)
    return await survey.aggregate()


@app.get(**docs.specifications['decode_access_token'])
async def decode_access_token(
        access_token: str = docs.arguments['access_token'],
    ):
    return access.decode(access_token)


@app.post(**docs.specifications['generate_access_token'])
async def generate_access_token(
        authentication_credentials: AuthenticationCredentials = (
            docs.arguments['authentication_credentials']
        ),
    ):
    return await account_manager.authenticate(
        authentication_credentials.identifier,
        authentication_credentials.password,
    )


@app.put(**docs.specifications['refresh_access_token'])
async def refresh_access_token(
        access_token: str = docs.arguments['access_token'],
    ):
    return access.generate(access.decode(access_token))


@app.post(**docs.specifications['verify_email_address'])
async def verify_email_address(
        verification_credentials: VerificationCredentials = (
            docs.arguments['verification_credentials']
        ),
    ):
    return await account_manager.verify(
        verification_credentials.verification_token,
        verification_credentials.password,
    )
