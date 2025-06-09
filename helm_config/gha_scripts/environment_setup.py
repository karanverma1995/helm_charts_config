import os
import json
import logging
import yaml
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.auth
from gha.resources.constants import production_projects

class EnvironmentSetup:
    """
    Class for setting up environment variables based on the GitHub event type.
    """

    def modify_GHA_environment(self, env_var, env_var_value, include_output=False):
        """
        Modifies the GitHub Actions environment file with the given environment variable and its value.

        Args:
            env_var (str): The name of the environment variable.
            env_var_value (str): The value of the environment variable.
        """
        if not os.getenv('CI'):
            logging.info("Not running in CI environment. Skipping modification of GitHub Actions environment.")
            logging.info(f"Output Var: {env_var}, Value: {env_var_value}")
            return None
        
        env_file = os.getenv('GITHUB_ENV')
        with open(env_file, 'r') as file:
            filedata = file.read()

        current_value = os.getenv(env_var, "")
        file_mode = 'w'
        environment_variable_string = f"{env_var}={env_var_value}"

        if env_var in filedata:
            environment_variable_string = filedata.replace(f"{env_var}={current_value}", environment_variable_string)
        else:
            file_mode = 'a'

        with open(env_file, file_mode) as env:
            print(environment_variable_string, file=env)
      
        if include_output:
            output_file = os.getenv('GITHUB_OUTPUT')
            with open(output_file, 'r') as file:
                filedata = file.read()

            current_value = os.getenv(env_var, "")
            file_mode = 'w'
            environment_variable_string = f"{env_var}={env_var_value}"

            if env_var in filedata:
                environment_variable_string = filedata.replace(f"{env_var}={current_value}", environment_variable_string)
            else:
                file_mode = 'a'

            with open(output_file, file_mode) as env:
                print(environment_variable_string, file=env)
                
    def get_branch_name(self):
        """
        Gets the branch name based on the GitHub event type.
        """        
        return self.set_branch_name(include_output=False)

    def set_branch_name(self, include_output='True'):
        """
        Sets the branch name based on the GitHub event type.
        """
        github_context = os.getenv('GITHUB_CONTEXT')
        if not github_context:
            raise ValueError("GITHUB_CONTEXT environment variable is not set")
            
        context = json.loads(github_context)
        logging.info(f"Event type: {context['event_name']}")

        if context['event_name'] == 'workflow_run':
            branch_name = context['event']['workflow_run']['head_branch']
        elif context['event_name'] == 'pull_request':
            branch_name = context['head_ref']
        else:
            branch_name = context['ref'].replace('refs/heads/', '')

        branch_name = branch_name.lower()
        if include_output:
            self.modify_GHA_environment('BRANCH', branch_name, include_output=True) 
        logging.info(f"Set Branch Name: {branch_name}")
        return branch_name

    def set_artifactory_repository(self, branch_name, project_type='default'):
        """
        Sets the Artifactory Repository based on the branch name and project type. Supports docker and python-lib

        Args:
            branch_name (str): The name of the branch.
            project_type (str): The type of the project
        """
        if not branch_name:
            logging.error("Branch name not provided. Exiting.")
            exit(1)
        if branch_name == "main":
            if project_type == "python-lib":
                artifactory_repo = "omni-pypi-prod"
            else:
                artifactory_repo = "omni-docker-prod"
        elif branch_name == "develop":
            if project_type == "python-lib":
                artifactory_repo = "omni-pypi-dev"
            else:
                artifactory_repo = "omni-docker-dev"
        else:
            if project_type == "python-lib":
                artifactory_repo = "omni-pypi-ci"
            else:
                artifactory_repo = "omni-docker-ci"
        self.modify_GHA_environment('ARTIFACTORY_REPO', artifactory_repo, include_output=True)
        logging.info(f"Set Artifactory Repository: {artifactory_repo}")       

    def set_env_type(self, etl_project, runner_type):
        """
        Determines the environment type based on the etlProject and the runners to be used.

        Args:
            etl_project (str): The name of the ETL project.
        """
        env_type = 'eng'  # Default value
        runner = f"garm-dev-us-east4-container-linux-{runner_type}-medium"
        if etl_project in production_projects:
            env_type = 'prd'
            region = etl_project.split('-')[3]
            match region:
                case '01' | 'use1':
                    runner_region = 'us-east1'
                case '02' | 'ca':
                    runner_region = 'na-ne1'
                case _:
                    runner_region = 'us-east1'
            runner = f"garm-prod-{runner_region}-container-linux-{runner_type}-medium"

        self.modify_GHA_environment('ENV_TYPE', env_type, include_output=True)      
        self.modify_GHA_environment('RUNNER', runner, include_output=True)
        logging.info(f"Set Environment Type: {env_type}")
        logging.info(f"Set Runner: {runner}")

    def set_artifactory_path(self, branch_name):
        """
        Sets the Artifactory Terraform Path based on the branch name.

        Args:
            branch_name (str): The name of the branch.
        """
        if branch_name == "main":
            artifactory_path = "omni-prod"
        else:
            artifactory_path = "omni-dev"

        self.modify_GHA_environment('ARTIFACTORY_PATH', artifactory_path, include_output=True)
        logging.info(f"Set Artifactory Path: {artifactory_path}")

    def set_terraform_version(self, artifact_name, workspace):
        """
        Sets the Terraform version based on the artifact name and workspace.

        Args:
            artifact_name (str): The name of the artifact.
            workspace (str): The workspace directory.
        """
        with open(os.path.join(workspace, 'deploy', artifact_name, 'src', 'main', 'terraform', 'terraform-metadata.yml')) as file:
            data = yaml.load(file, Loader=yaml.FullLoader)
            tf_version = data.get('terraformVersion', '')
            logging.info(f"tf_version: {tf_version}")
        self.modify_GHA_environment('TF_VERSION', tf_version, include_output=True)   
        logging.info(f"The current terraform version is: {tf_version}")

    def set_artifact_version(self, artifact_name, artifact_version, workspace):
        """
        Sets the artifact version based on the artifact name, version, and workspace.

        Args:
            artifact_name (str): The name of the artifact.
            artifact_version (str): The version of the artifact.
            workspace (str): The workspace directory.
        """
        logging.info("Setting Artifact Version")
        if artifact_version is None or artifact_version == "" or artifact_version == 0:
            logging.info("No artifact version provided. Loading version from terraform-metadata file")
            with open(os.path.join(workspace, 'deploy', artifact_name, 'src', 'main', 'terraform', 'terraform-metadata.yml')) as file:
                data = yaml.load(file, Loader=yaml.FullLoader)
                af_version = data.get('version', '')
            logging.info(f"The current version is: {af_version}")
        else:
            artifact_version = artifact_version.replace("%", "").replace("\r", "").replace("\n", "")
            af_version = artifact_version
            logging.info(f"Artifact version provided: {af_version}")
        self.modify_GHA_environment('ARTIFACT_VER', af_version, include_output=True)

    def set_working_directory(self, artifact_name, workspace):
        """
        Sets the working directory for the artifact.

        Args:
            artifact_name (str): The name of the artifact.
            workspace (str): The workspace directory.
        """
        working_directory = f"{workspace}/extracted_{artifact_name}"
        self.modify_GHA_environment('WORKING_DIR', working_directory, include_output=True)                                       
        logging.info(f"Set Working Directory: {workspace}/extracted_{artifact_name}")
