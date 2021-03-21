import os

from fastapi import FastAPI, Path, Query, Body, Form, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.security import OAuth2PasswordBearer
from pymongo import MongoClient, ASCENDING

from app.mailing import Letterbox
from app.account import AccountManager
from app.survey import SurveyManager
from app.cryptography import JWTManager


# check that required environment variables are set
assert all([
    os.getenv(var)
    for var
    in [
        'ENVIRONMENT',
        'FRONTEND_URL',
        'BACKEND_URL',
        'PUBLIC_RSA_KEY',
        'PRIVATE_RSA_KEY',
        'MONGODB_CONNECTION_STRING',
        'MAILGUN_API_KEY',
    ]
])


# development / production / testing environment
ENVIRONMENT = os.getenv('ENVIRONMENT')
# MongoDB connection string
MONGODB_CONNECTION_STRING = os.getenv('MONGODB_CONNECTION_STRING')


# connect to mongodb via pymongo
client = MongoClient(MONGODB_CONNECTION_STRING)
# get link to development / production / testing database
database = client[ENVIRONMENT]
# set up database indices synchronously via pymongo
database['configurations'].create_index(
    keys=[('username', ASCENDING), ('survey_name', ASCENDING)],
    name='username_survey_name_index',
    unique=True,
)
database['accounts'].create_index(
    keys='email_address',
    name='email_address_index',
    unique=True,
)
database['accounts'].create_index(
    keys='verification_token',
    name='verification_token_index',
    unique=True,
)
database['accounts'].create_index(
    keys='creation_time',
    name='creation_time_index',
    expireAfterSeconds=10*60,  # delete draft accounts after 10 mins
    partialFilterExpression={'verified': {'$eq': False}},
)


# create fastapi app
app = FastAPI()
# connect to mongodb via motor
client = AsyncIOMotorClient(MONGODB_CONNECTION_STRING)
# get link to development / production / testing database
database = client[ENVIRONMENT]
# create email client
letterbox = Letterbox()
# create JWT manager
jwt_manager = JWTManager()
# instantiate survey manager
survey_manager = SurveyManager(database, letterbox, jwt_manager)
# instantiate account manager
account_manager = AccountManager(
    database,
    letterbox,
    jwt_manager,
    survey_manager,
)
# fastapi password bearer
oauth2_scheme = OAuth2PasswordBearer('/authentication')


PAR_USERNAME = Path(
    ...,
    description='The name of the user',
    example='fastsurvey',
)
PAR_EMAIL = Form(
    ...,
    description='The users\'s email address',
    example='support@fastsurvey.io',
)
PAR_PASSWORD = Form(
    ...,
    description='The account password',
    example='12345678',
)
PAR_SURVEY_NAME = Path(
    ...,
    description='The name of the survey',
    example='hello-world',
)
PAR_CONFIGURATION = Body(..., description='The new configuration')


@app.get(
    path='/users/{username}',
    responses={
        200: {
            'content': {
                'application/json': {
                    'example': {
                        'username': 'fastsurvey',
                        'email_address': 'support@fastsurvey.io',
                        'verified': True,
                    }
                }
            }
        }
    },
)
async def fetch_user(
        username: str = PAR_USERNAME,
        access_token: str = Depends(oauth2_scheme),
    ):
    """Fetch the given user's account data."""
    return await account_manager.fetch(username, access_token)


@app.post('/users/{username}')
async def create_user(
        username: str = PAR_USERNAME,
        email: str = PAR_EMAIL,
        password: str = PAR_PASSWORD,
    ):
    """Create a new user with default account data."""
    await account_manager.create(username, email, password)


@app.put('/users/{username}')
async def update_user(
        username: str = PAR_USERNAME,
        account_data: dict = Body(
            ...,
            description='The updated account data',
        ),
        access_token: str = Depends(oauth2_scheme),
    ):
    """Update the given user's account data."""
    return await account_manager.update(username, account_data, access_token)


@app.delete('/users/{username}')
async def delete_user(
        username: str = PAR_USERNAME,
        access_token: str = Depends(oauth2_scheme),
    ):
    """Delete the user and all her surveys from the database."""
    return await account_manager.delete(username, access_token)


@app.get('/users/{username}/surveys')
async def fetch_configurations(
        username: str = PAR_USERNAME,
        skip: int = Query(
            0,
            description='The index of the first returned configuration',
            example=0,
        ),
        limit: int = Query(
            10,
            description='The query result count limit; 0 means no limit',
            example=10,
        ),
        access_token: str = Depends(oauth2_scheme),
    ):
    """Fetch the user's configurations sorted by the start date."""
    return await account_manager.fetch_configurations(
        username,
        skip,
        limit,
        access_token,
    )


@app.get('/users/{username}/surveys/{survey_name}')
async def fetch_configuration(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
    ):
    """Fetch the configuration document of a given survey."""
    return await survey_manager.fetch(username, survey_name)


@app.post('/users/{username}/surveys/{survey_name}')
async def create_survey(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
        configuration: dict = PAR_CONFIGURATION,
        access_token: str = Depends(oauth2_scheme),
    ):
    """Create new survey with given configuration."""
    await survey_manager.create(
        username,
        survey_name,
        configuration,
        access_token,
    )


@app.put('/users/{username}/surveys/{survey_name}')
async def update_survey(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
        configuration: dict = PAR_CONFIGURATION,
        access_token: str = Depends(oauth2_scheme),
    ):
    """Update survey with given configuration."""
    await survey_manager.update(
        username,
        survey_name,
        configuration,
        access_token,
    )


@app.delete('/users/{username}/surveys/{survey_name}')
async def delete_survey(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
        access_token: str = Depends(oauth2_scheme),
    ):
    """Delete given survey including all its submissions and other data."""
    await survey_manager.delete(username, survey_name, access_token)


@app.post('/users/{username}/surveys/{survey_name}/submissions')
async def submit(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
        submission: dict = Body(
            ...,
            description='The user submission',
        ),
    ):
    """Validate submission and store it under pending submissions."""
    survey = await survey_manager._fetch(username, survey_name)
    return await survey.submit(submission)


@app.delete('/users/{username}/surveys/{survey_name}/submissions')
async def reset_survey(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
        access_token: str = Depends(oauth2_scheme),
    ):
    """Reset a survey by delete all submission data including any results."""
    await survey_manager.reset(username, survey_name, access_token)


@app.get('/users/{username}/surveys/{survey_name}/verification/{token}')
async def verify(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
        token: str = Path(..., description='The verification token'),
    ):
    """Verify user token and either fail or redirect to success page."""
    survey = await survey_manager._fetch(username, survey_name)
    return await survey.verify(token)


@app.get('/users/{username}/surveys/{survey_name}/results')
async def aggregate(
        username: str = PAR_USERNAME,
        survey_name: str = PAR_SURVEY_NAME,
    ):
    """Fetch the results of the given survey."""

    # TODO adapt result following authentication

    survey = await survey_manager._fetch(username, survey_name)
    return await survey.aggregate()


@app.post('/authentication')
async def authenticate(
        identifier: str = Form(
            ...,
            description='The account email or the username',
            example='fastsurvey',
        ),
        password: str = PAR_PASSWORD,
    ):
    return await account_manager.authenticate(identifier, password)


@app.post('/verification')
async def verify_email_address(
        token: str = Form(..., description='The account verification token'),
        password: str = PAR_PASSWORD,
    ):
    return await account_manager.verify(token, password)
