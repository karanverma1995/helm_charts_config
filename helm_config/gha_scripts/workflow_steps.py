import os
import fire
import google.auth
import json
import logging
import re
import shutil
import tarfile
import urllib.request
import time

from pathlib import Path

# third-party
from gha.gha_environment_setup import EnvironmentSetup
from gha.gha_gcputils import GHAGCPUtils


logging.basicConfig(level=logging.INFO)
artifact_url = "ukgartifactory.pe.jfrog.io/artifactory"
scripts_dir = os.path.dirname(os.path.abspath(os.curdir))
ROOT_DIR = Path(scripts_dir).parent

if(os.environ.get('GITHUB_WORKSPACE')):
    ROOT_DIR = os.environ.get('GITHUB_WORKSPACE')

class GHA(GHAGCPUtils):
    """
    Class representing the GitHub Actions workflow steps.
    """
    def __init__(self):
        super().__init__()
        self.env_setup = EnvironmentSetup()

    def setup_environment(self, set_env='all'):
        """
        Sets up the environment variables based on the GitHub event type.
        """
        set_type = set_env.lower().strip()
        branch = ""
        if set_type in ['branch', 'all']:
            branch = self.env_setup.set_branch_name()
        if set_type in ['artifactory', 'all']:
            branch_value = os.getenv('BRANCH') if os.getenv('BRANCH') else self.env_setup.get_branch_name() if branch == "" else branch
            project_type = os.getenv('PROJECT_TYPE') if os.getenv('PROJECT_TYPE') else 'default'
            self.env_setup.set_artifactory_repository(branch_value, project_type)
            self.env_setup.set_artifactory_path(branch_value)
        if set_type in ['env_type', 'all']:
            self.env_setup.set_env_type(os.getenv('ETLPROJECT'), os.getenv('RUNNERTYPE', 'mega'))
        if set_type in ['artifact_version', 'all']:
            # Artifacter Version used to be set as in input but that was removed, functionality to support this use case remains
            self.env_setup.set_artifact_version(os.getenv('ARTIFACT_NAME'), os.getenv('ARTIFACT_VERSION'), os.getenv('GITHUB_WORKSPACE'))
        if set_type in ['terraform_version', 'all']:
            self.env_setup.set_terraform_version(os.getenv('ARTIFACT_NAME'), os.getenv('GITHUB_WORKSPACE'))
        if set_type in ['work_dir', 'all']:                    
            self.env_setup.set_working_directory(os.getenv('ARTIFACT_NAME'), os.getenv('GITHUB_WORKSPACE'))

    def extract_artifacts(self, response, artifact_name):
        """
        Extracts the artifacts from the response and saves them to the extracted directory.

        Args:
            response (object): The response object containing the artifacts.
            artifact_name (str): The name of the artifact.
        """
        try:
            logging.info(f"Extracting {artifact_name} to {ROOT_DIR}/extracted_{artifact_name}")
            tar = tarfile.open(fileobj=response, mode="r|gz")
            tar.extractall(path=f"{ROOT_DIR}/extracted_{artifact_name}")
            tar.close()
            logging.info(f"Extraction Completed")
        except Exception as e:
            logging.error(f"Error extracting artifact: {e}")

    def download_artifacts(self, artifact_name, artifact_version, artifact_path):
        """
        Downloads the artifacts from the artifact URL and extracts them.

        Args:
            artifact_name (str): The name of the artifact.
            artifact_version (str): The version of the artifact.
            artifact_path (str): The path to the artifact.
        """
        try:
            logging.info(f"Creating directory {ROOT_DIR}/extracted_{artifact_name}")
            os.makedirs(f"{ROOT_DIR}/extracted_{artifact_name}", exist_ok=True)
        except Exception as e:
            logging.error(f"Error creating directory: {e}")

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logging.info(f"Attempt #{attempt} to download {artifact_name} version {artifact_version} from {artifact_path}")
                response = urllib.request.urlopen(f'http://{artifact_url}/{artifact_path}/{artifact_name}/{artifact_version}')
                logging.info(f"Download Completed")
                self.extract_artifacts(response, artifact_name)
                break
            except Exception as e:
                logging.error(f"Attempt #{attempt} failed to download artifact: {e}")
                if attempt != max_attempts:
                    logging.info(f"Beginning next attempt in 5 seconds...")
                    time.sleep(5)
                else:
                    logging.error(f"All {max_attempts} attempts failed. Exiting.")
                    exit(1)

    def copy_terraform_environment_tfvars(self, artifact_name, working_directory):
        """
        Copies the Terraform environment variables to the working directory.

        Args:
            artifact_name (str): The name of the artifact.
            workspace (str): The workspace directory.
            working_directory (str): The working directory.
        """
        logging.info("Copying Terraform Environment Variables")
        try:
            terraform_dir = f"{ROOT_DIR}/deploy/{artifact_name}/environments/"
            logging.info(f"Terraform directory: {terraform_dir}")
            destination_dir = f"{working_directory}/environments/"

            # Create the destination directory if it does not exist
            os.makedirs(destination_dir, exist_ok=True)

            # Copy all files and folders from terraform_dir to destination_dir
            for item in os.listdir(terraform_dir):
                src_path = os.path.join(terraform_dir, item)
                dst_path = os.path.join(destination_dir, item)
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)

            logging.info("Copy complete")
        except Exception as e:
            logging.error(f"Error copying tfvars file: {e}")

    def set_wif_provider_and_svc(self, project, domain="kronos"):
        """
        Sets the WIF provider and WIF service account based on the project.

        Args:
            etl_project (str): The name of the project.
        """
        ## Checkbox for kronos versus ulti
        ## svc-deploy@p-ulti-data-pfplatform-01-164f.iam.gserviceaccount.com
        if domain == "kronos":
            self.set_wif_provider_and_svc_kronos(project)
        else:
            self.set_wif_provider_and_svc_ulti(project)
  
    def set_wif_provider_and_svc_ulti(self, project):
        env_type = project.split("-")[0]
        
        if env_type == "d":
            wif_provider = "projects/545511040973/locations/global/workloadIdentityPools/runners/providers/github"
            # DEV Acceleration Reference: https://devportal.ukg.int/docs/default/component/cloud-engine/gcp/wif
            wif_svc = "svc-deploy-de@d-ulti-data-pfplatform-01-721d.iam.gserviceaccount.com"
        else:
            wif_provider = "projects/548359843085/locations/global/workloadIdentityPools/runners/providers/github"
            wif_svc = "svc-deploy-de@p-ulti-data-pfplatform-01-164f.iam.gserviceaccount.com "
            # DEV Acceleration Reference: https://devportal.ukg.int/docs/default/component/cloud-engine/gcp/wif
        
        logging.info(f"Setting WIF Provider: {wif_provider}")
        logging.info(f"Setting WIF Service Account: {wif_svc}")

        self.env_setup.modify_GHA_environment("WIF_PROVIDER", wif_provider, include_output=True)
        self.env_setup.modify_GHA_environment("WIF_SVC", wif_svc, include_output=True)
    
    def set_wif_provider_and_svc_kronos(self, project):
        env_type = project.split("-")[2]
        workflow = os.environ.get('WORKFLOW','default')
        # 3/05/2025 removed logic to set wif_provider based on people-fabric or omni-dhub
        # Since we will not be deploying to datahub environments anymore we will always use omni-dhub
        if env_type == "eng":
            wif_provider = "projects/448412351035/locations/global/workloadIdentityPools/omni-dhub/providers/github"
            # This is to support system test workflow in Pro Batch repo
            # Workflow will need an account that has more access in order to create and delete objects in GCS
            if workflow == 'test':
                wif_svc = "svc-dhub-eng-master-dev@repd-e-eng-adm-01.iam.gserviceaccount.com"
            else:
                wif_svc = "svc-data-hub-deploy-eng-adm@repd-e-eng-adm-01.iam.gserviceaccount.com"
        else:
            wif_provider = "projects/99376011528/locations/global/workloadIdentityPools/omni-dhub/providers/github"
            wif_svc = "svc-data-hub-deploy-noneng@repd-a-adm-01.iam.gserviceaccount.com"
            

        logging.info(f"Setting WIF Provider: {wif_provider}")
        logging.info(f"Setting WIF Service Account: {wif_svc}")

        self.env_setup.modify_GHA_environment("WIF_PROVIDER", wif_provider, include_output=True)
        self.env_setup.modify_GHA_environment("WIF_SVC", wif_svc, include_output=True)

    def set_impersonation_account(self, project, domain="kronos"):
        """
        Sets the impersonation account based on the project.

        Args:
            project (str): The name of the project.
        """
        if domain == "kronos":
            self.set_impersonation_account_kronos(project)
        else:
            self.set_impersonation_account_ulti(project)
    
    def set_impersonation_account_kronos(self, project):
        env_type = project.split("-")[2]
        env_number = project.split("-")[3]
        impersonate_svc = f"svc-repd-{env_type}-{env_number}@{project}.iam.gserviceaccount.com"
        logging.info(f"Setting Impersonation Account: {impersonate_svc}")
        logging.info(f"IMPERSONATE_SVC={impersonate_svc}")

        self.env_setup.modify_GHA_environment("IMPERSONATE_SVC", impersonate_svc, include_output=True)
    
    def set_impersonation_account_ulti(self, project):
        impersonate_svc = f"svc-platform@{project}.iam.gserviceaccount.com"
        logging.info(f"Setting Impersonation Account: {impersonate_svc}")
        logging.info(f"IMPERSONATE_SVC={impersonate_svc}")

        self.env_setup.modify_GHA_environment("IMPERSONATE_SVC", impersonate_svc, include_output=True)

    def set_auth_access_token(self, token):
        """
        Sets the GitHub OAuth access token in the GitHub environment.
        """
        logging.info(f"Setting Google OAuth Access Token: {token}")
        self.env_setup.modify_GHA_environment("GOOGLE_OAUTH_ACCESS_TOKEN", token, include_output=True)
    
    def generate_backend_config(self, project, artifact, working_directory):
        logging.info("Starting Backend Config Generation")
        backend_config = f"""terraform {{
        backend "gcs" {{
            bucket  = "{project}-terraform-state"
            prefix  = "{artifact}"
        }}
        }}"""
        try:
            file_path = f'{working_directory}/backend.tf'
            with open(file_path, 'w') as file:
                file.write(backend_config)
            logging.info(f"Backend file path: {file_path}")
            logging.info("Backend Config Generation Completed")
            logging.info(f"Backend Config: {backend_config}")
        except Exception as e:
            logging.error(f"Error generating backend config: {e}")
                    
    def read_tfvars(self, tfvars_file_path, field):
        """
        Reads a field from a tfvars file.
        args:
            tfvars_file_path (str): The path to the tfvars file.
            field (str): The field to read.        
        """
        file_path = os.path.join(ROOT_DIR, tfvars_file_path)
        self.check_if_file_exists(file_path)

        with open(file_path, 'r') as file:
            lines = file.readlines()
        
        tfvars = {}
        for line in lines:
            if '=' in line:
                key, value = line.split('=', 1)
                if key.strip() == field:
                    return value.strip().strip('"')
        return None
    
    def get_dataflow_job_name(self, projectId, workspace, update_job, parallel_job, job_name_override, tf_operation='apply'):
        """
        Returns the Dataflow job name.
        args:
            projectId (str): The project ID.
            update_job (str): The update job flag.
            workspace (str): The workspace (alt-config)            
        """
        # Read the job_name and region from the tfvars files
        region = self.read_tfvars(
            f'deploy/pfab-strm-dataflow-terraform/environments/{projectId}.tfvars', 'region')
        job_var_file = 'deploy/pfab-strm-dataflow-terraform/environments/shared.auto.tfvars'                      
        job_name = self.read_tfvars(job_var_file, 'dataflow_job_name')

        try:
            target_job_name, previous_job_name = self.get_df_job_name(projectId, region, workspace, job_name, update_job, parallel_job, job_name_override, tf_operation)
            self.env_setup.modify_GHA_environment('DATAFLOW_JOB_NAME', target_job_name, include_output=True)            
            self.env_setup.modify_GHA_environment('DATAFLOW_JOB_NAME_PP_DESTROY', previous_job_name, include_output=True)
           
        except Exception as e:
            logging.error(f"Error getting Dataflow job name: {e}")        
    
    # If the workspace is set to default, then the default workspace/project-specific alt-config is used.
    # If the workspace is set to dev, then the default workspace/ dev alt-config is used.
    # If the workspace is set to a specific workspace, then the specific workspace/alt-config is used.
    # If the workspace does not have a corresponding alt-config, 
    # then set the specific workspace, and use default/project-specific alt-config.
    # If the workspace is not found, then the default workspace/project-specific alt-config is used.
    # If using parallel job deployment, then the workspace is set to workspace1 to differentiate it, when deploying.
    # The workspace flips between workspace1 and workspace to handle parallel pipeline deployments.  
    def set_terraform_workspace(self, workspace):
        """
        Sets the Terraform workspace based on if the job name contains a 1 indicating this is a parallel pipeline deployed on the pp workspace.  
        args:
            workspace (str): The workspace to set.            
        """        
        job_name = os.getenv('DATAFLOW_JOB_NAME')
        if not job_name:
            logging.error("DATAFLOW_JOB_NAME environment variable is not set. Defaulting to argument workspace.")
            job_name = ""  # Set job_name to an empty string to avoid TypeError

        is_default = True if workspace == 'default' or workspace == 'dev' else False        
        workspace = 'default' if is_default else workspace.lower().strip()
        pp_workspace = f"default1" if is_default else f'{workspace}1'

        # If the job name contains a 1, then set the workspace to the parallel pipeline workspace
        if '1-' in job_name:    
            logging.info(f"Setting Terraform workspace to {pp_workspace}")
            assign_workspace = pp_workspace
        else:
            logging.info(f"Setting Terraform workspace to {workspace}")
            assign_workspace = workspace
        
        self.env_setup.modify_GHA_environment('TF_WORKSPACE', assign_workspace, include_output=True)
        pp_destroy_workspace = self.toggle_workspace(assign_workspace)
        self.env_setup.modify_GHA_environment('TF_WORKSPACE_PP_DESTROY', pp_destroy_workspace, include_output=True)
    
    def toggle_workspace(self, workspace):
        """
        Toggles the workspace based on the indicator (1).
        args:
            workspace (str): The workspace.
        """
        if '1' in workspace:
            # Remove '1' from the workspace name
            new_workspace = workspace.replace('1', '')
        else:
            # Add '1' to the workspace name
            new_workspace = f'{workspace}1'
        return new_workspace    

      
def main():
    fire.Fire(GHA)

if __name__ == "__main__":
    main()
