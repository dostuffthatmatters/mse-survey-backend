import pytest
import pydantic

import app.validation as validation


@pytest.fixture(scope='module')
def submission_validators(configurations):
    """Provide submission validator for every test survey."""
    return {
        survey_name: validation.SubmissionValidator.create(
            configurations
        )
        for survey_name, configurations
        in configurations.items()
    }


################################################################################
# Account Validation
################################################################################


def test_account_data_passing(account_datas):
    """Test that account validation passes some valid accounts."""
    for account_data in account_datas:
        validation.AccountData(**account_data)


def test_account_data_failing(invalid_account_datas):
    """Test that account validation fails some invalid accounts."""
    for account_data in invalid_account_datas:
        with pytest.raises(pydantic.ValidationError):
            validation.AccountData(**account_data)


################################################################################
# Configuration Validation
################################################################################


def test_configurations_passing(configurations):
    """Test that configuration validation passes some valid configurations."""
    for configuration in configurations.values():
        validation.Configuration(**configuration)


def test_configurations_failing(invalid_configurationss):
    """Test that configuration validation fails some invalid configurations."""
    for invalid_configurations in invalid_configurationss.values():
        for configuration in invalid_configurations:
            with pytest.raises(pydantic.ValidationError):
                validation.Configuration(**configuration)


################################################################################
# Submission Validation
################################################################################


def test_generating_submission_validation_schema(configurations, schemas):
    """Test that the schema generation function returns the correct result."""
    for survey_name, configuration in configurations.items():
        schema = validation.SubmissionValidator._generate_validation_schema(
            configuration
        )
        assert schema == schemas[survey_name]


def test_submissions_passing(submission_validators, submissionss):
    """Test that submission validator passes some valid submissions."""
    for survey_name, submissions in submissionss.items():
        for submission in submissions:
            assert submission_validators[survey_name].validate(submission)


def test_submissions_failing(submission_validators, invalid_submissionss):
    """Test that submission validator fails some invalid submissions."""
    for survey_name, invalid_submissions in invalid_submissionss.items():
        for submission in invalid_submissions:
            assert not submission_validators[survey_name].validate(submission)
