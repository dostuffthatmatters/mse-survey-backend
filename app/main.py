import fastapi
import fastapi.middleware.cors
import fastapi.exceptions
import pydantic

import app.account as acn
import app.survey as sve
import app.documentation as docs
import app.settings as settings
import app.validation as validation
import app.authentication as auth
import app.utils as utils
import app.errors as errors


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
    allow_methods=['*'],
    allow_headers=['*'],
)


# add pydantic ValidationError exception handler
@app.exception_handler(pydantic.ValidationError)
async def validation_error_exception_handler(request, exc):
    return fastapi.responses.JSONResponse(
        status_code=errors.InvalidSyntaxError.STATUS_CODE,
        content={'detail': errors.InvalidSyntaxError.DETAIL},
    )

# add fastapi RequestValidationError exception handler
@app.exception_handler(fastapi.exceptions.RequestValidationError)
async def request_validation_error_exception_handler(request, exc):
    return fastapi.responses.JSONResponse(
        status_code=errors.InvalidSyntaxError.STATUS_CODE,
        content={'detail': errors.InvalidSyntaxError.DETAIL},
    )


################################################################################
# Routes
################################################################################


@app.get(**docs.SPECIFICATIONS['read_status'])
async def read_status():
    """Return some status information about the server."""
    return dict(
        environment=settings.ENVIRONMENT,
        commit_sha=settings.COMMIT_SHA,
        branch_name=settings.BRANCH_NAME,
        start_time=settings.START_TIME,
    )


@app.get(**docs.SPECIFICATIONS['read_user'])
@auth.authorize
async def read_user(
        data: validation.ReadUserRequest = fastapi.Depends(),
    ):
    """Fetch the given user's account data."""
    return await acn.read(data.username)


@app.post(**docs.SPECIFICATIONS['create_user'])
async def create_user(
        data: validation.CreateUserRequest = fastapi.Depends(),
    ):
    """Create a new user based on the given account data."""
    await acn.create(data.account_data.dict())


@app.put(**docs.SPECIFICATIONS['update_user'])
@auth.authorize
async def update_user(
        data: validation.UpdateUserRequest = fastapi.Depends(),
    ):
    """Update the given user's account data."""
    await acn.update(data.username, data.account_data.dict())


@app.delete(**docs.SPECIFICATIONS['delete_user'])
@auth.authorize
async def delete_user(
        data: validation.DeleteUserRequest = fastapi.Depends(),
    ):
    """Delete the user and all their surveys from the database."""
    await acn.delete(data.username)


@app.get(**docs.SPECIFICATIONS['read_surveys'])
@auth.authorize
async def read_surveys(
        data: validation.ReadSurveysRequest = fastapi.Depends(),
    ):
    """Fetch all of the user's survey configurations.

    As this is a protected route, configurations of surveys that are in
    draft mode **are** returned.

    """
    return await acn.read_configurations(data.username)


@app.get(**docs.SPECIFICATIONS['read_survey'])
async def read_survey(
        data: validation.ReadSurveyRequest = fastapi.Depends(),
    ):
    """Fetch a survey configuration.

    As this is an unprotected route, configurations of surveys that are in
    draft mode **are not** returned. When outside the start/end limits of a
    survey, only some meta information are returned.

    """
    configuration = await sve.read(
        data.username,
        data.survey_name,
        return_drafts=False,
    )
    timestamp = utils.now()
    exclude = ['_id']
    if (
        configuration['start'] is not None
        and timestamp < configuration['start']
        or configuration['end'] is not None
        and timestamp >= configuration['end']
    ):
        exclude += ['fields', 'max_identifier']
    return {k: v for k, v in configuration.items() if k not in exclude}


@app.post(**docs.SPECIFICATIONS['create_survey'])
@auth.authorize
async def create_survey(
        data: validation.CreateSurveyRequest = fastapi.Depends(),
    ):
    """Create new survey with given configuration."""
    await sve.create(data.username, data.configuration.dict(by_alias=True))


@app.put(**docs.SPECIFICATIONS['update_survey'])
@auth.authorize
async def update_survey(
        data: validation.UpdateSurveyRequest = fastapi.Depends(),
    ):
    """Update survey with given configuration."""
    await sve.update(
        data.username,
        data.survey_name,
        data.configuration.dict(by_alias=True),
    )


@app.delete(**docs.SPECIFICATIONS['delete_survey'])
@auth.authorize
async def delete_survey(
        data: validation.DeleteSurveyRequest = fastapi.Depends(),
    ):
    """Delete given survey including all its submissions and other data."""
    await sve.delete(data.username, data.survey_name)


@app.get(**docs.SPECIFICATIONS['export_submissions'])
@auth.authorize
async def export_submissions(
        data: validation.ReadSubmissionsRequest = fastapi.Depends(),
    ):
    """Export the submissions of a survey in a consistent format."""
    survey = await sve.fetch(data.username, data.survey_name)
    return await survey.export_submissions()


@app.post(**docs.SPECIFICATIONS['create_submission'])
async def create_submission(
        data: validation.CreateSubmissionRequest = fastapi.Depends(),
    ):
    """Validate submission and store it under pending submissions."""
    survey = await sve.fetch(
        data.username,
        data.survey_name,
        return_drafts=False,
    )
    survey.Submission(**data.submission)
    return await survey.submit(data.submission)


@app.delete(**docs.SPECIFICATIONS['reset_survey'])
@auth.authorize
async def reset_survey(
        data: validation.ResetSurveyRequest = fastapi.Depends(),
    ):
    """Reset a survey by deleting all submission data including any results."""
    await sve.reset(data.username, data.survey_name)


@app.post(**docs.SPECIFICATIONS['verify_submission'])
async def verify_submission(
        data: validation.VerifySubmissionRequest = fastapi.Depends(),
    ):
    """Verify a submission given the verification token sent via email."""
    survey = await sve.fetch(
        data.username,
        data.survey_name,
        return_drafts=False,
    )
    return await survey.verify(data.verification_credentials.verification_token)


@app.get(**docs.SPECIFICATIONS['read_results'])
@auth.authorize
async def read_results(
        data: validation.ReadResultsRequest = fastapi.Depends(),
    ):
    """Fetch the results of the given survey."""
    survey = await sve.fetch(data.username, data.survey_name)
    return await survey.aggregate()


@app.post(**docs.SPECIFICATIONS['login'])
async def login(
        data: validation.LoginRequest = fastapi.Depends(),
    ):
    """Generate an access token used to authenticate to protected routes."""
    return await acn.login(
        data.authentication_credentials.identifier,
        data.authentication_credentials.password,
    )


@app.delete(**docs.SPECIFICATIONS['logout'])
async def logout(
        data: validation.LogoutRequest = fastapi.Depends(),
    ):
    """Logout a user by rendering their access token useless."""
    return await acn.logout(data.access_token)


@app.post(**docs.SPECIFICATIONS['verify_account_email_address'])
async def verify_account_email_address(
        data: validation.VerifyAccountEmailAddressRequest = fastapi.Depends(),
    ):
    """Verify an email address given the verification token sent via email."""
    return await acn.verify(data.verification_credentials.verification_token)
