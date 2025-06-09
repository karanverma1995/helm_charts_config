import logging
import os
import fire
import json
from google.cloud import storage
import google.auth
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.api_core.exceptions import Forbidden, GoogleAPIError, NotFound
from google.auth import impersonated_credentials
from google.cloud import artifactregistry_v1
from gha.gha_dataflow import DataflowJob
from gha.gha_utilities import GHAUtilities
from gha.gha_workflow_summary import GHAWorkflowSummary
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, TryAgain
from gha.resources.constants import MAX_TRIES, BACK_OFF_TIME

class GHAGCPUtils(GHAUtilities, GHAWorkflowSummary):
    
    def __init__(self):
        super().__init__()
        
    def setup_auth(self):
        """
        Sets up Google authentication credentials.
        """
        if os.environ.get('CI'):
            logging.info("Running in CI environment")
            self.credentials, _ = google.auth.default()
        else:
            # Local development
            logging.info("Running in local environment")
            deployment_auth = json.loads(open(os.environ['GOOGLE_APPLICATION_CREDENTIALS']).read())    
            self.credentials = service_account.Credentials.from_service_account_info(deployment_auth)

    def get_deployment_credentials(self):
        """
        Returns the deployment credentials based on the environment.
        
        Returns:
            google.auth.credentials.Credentials: The deployment credentials.
        """
        if os.environ.get('CI'):
            logging.info("Running in CI environment")
            deployment_cred, _ = google.auth.default()
        else:
            # Local development
            logging.info("Running in local environment")
            etl_project = 'd-ulti-data-pfplatform-01-721d'
            deployment_auth = json.loads(open(os.environ['GOOGLE_APPLICATION_CREDENTIALS']).read())    
            deployment_cred = service_account.Credentials.from_service_account_info(deployment_auth)
        
        return deployment_cred
    
    def bucket_exists(self, bucket_name, etl_project, deployment_cred):
        """
        Checks if a Google Cloud Storage bucket exists.

        Args:
            bucket_name (str): The name of the bucket.
            etl_project (str): The name of the ETL project.
            deployment_cred (object): The deployment credentials.

        Returns:
            bool: True if the bucket exists, False otherwise.
        """
        try:
            storage_client = storage.Client(project=etl_project, credentials=deployment_cred)
            bucket = storage_client.lookup_bucket(bucket_name)
            if bucket is None:
                return False
            else:
                # Try to get the bucket to check if we own it
                storage_client.get_bucket(bucket_name)
                logging.info(f"Bucket {bucket_name} already exists")
                return True
        except google.api_core.exceptions.Forbidden:
            return False

    @retry(
        retry=(retry_if_exception_type()),
        stop=stop_after_attempt(MAX_TRIES),
        wait=wait_fixed(BACK_OFF_TIME),
        reraise=True
    )
    def create_gcs_bucket(self, bucket_name, etl_project, region, deployment_cred):
        """
        Creates a Google Cloud Storage bucket.

        Args:
            bucket_name (str): The name of the bucket.
            etl_project (str): The name of the ETL project.
            region (str): The region of the bucket.
            deployment_cred (object): The deployment credentials.
        """
        try:
            count = self.create_gcs_bucket.retry.statistics.get("attempt_number") or self.create_gcs_bucket.statistics.get("attempt_number")
            storage_client = storage.Client(project=etl_project, credentials=deployment_cred)
            storage_client.create_bucket(bucket_name, location=region)
            logging.info(f"Bucket {bucket_name} created")
            
        except TryAgain as e:
            raise e
        except GoogleAPIError as e:
            if count < MAX_TRIES:
                logging.warning(f"Retrying due to GoogleAPIError creating bucket {bucket_name} in project {etl_project} in region {region}: {e}")
            else:
                logging.error(f"GoogleAPIError creating bucket {bucket_name} in project {etl_project} in region {region}: {e}")
            raise e
        except Exception as e:
            if count < MAX_TRIES:
                logging.warning(f"Retrying due to unexpected error creating bucket {bucket_name} in project {etl_project} in region {region}: {e}")
            else:
                logging.error(f"Unexpected error creating bucket {bucket_name} in project {etl_project} in region {region}: {e}")
            raise e

    def impersonate_service_account(self, deployment_cred, impersonation_svc):
        """
        Impersonates a service account.

        Args:
            deployment_cred (object): The deployment credentials.
            impersonation_svc (str): The service account to impersonate.

        Returns:
            object: The impersonated credentials.
        """
        try:
            target_credentials = impersonated_credentials.Credentials(
                source_credentials=deployment_cred,
                target_principal=impersonation_svc,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                lifetime=3600,
            )
        except Exception as e:
            logging.error(f"Error impersonating service account: {e}")
        return target_credentials
    
    @retry(
        retry=(retry_if_exception_type()),
        stop=stop_after_attempt(MAX_TRIES),
        wait=wait_fixed(BACK_OFF_TIME),
        reraise=True
    )
    def update_bucket(self, bucket_name, etl_project, env_type, substream_id, deployment_cred, impersonation_svc ):
        """
        Updates a Google Cloud Storage bucket with labels and versioning enabled.

        Args:
            bucket_name (str): The name of the bucket.
            etl_project (str): The name of the ETL project.
            env_type (str): The type of the deployment environment.
            substream_id (str): The substream ID.
            deployment_cred (object): The deployment credentials.
            impersonation_svc (str): The service account to impersonate.
        """
        try:
            count = self.update_bucket.retry.statistics.get("attempt_number") or self.update_bucket.statistics.get("attempt_number")
            storage_client = storage.Client(project=etl_project, credentials=self.impersonate_service_account(deployment_cred, impersonation_svc))
            bucket = storage_client.get_bucket(bucket_name)
            bucket.iam_configuration.uniform_bucket_level_access_enabled = True
            bucket.versioning_enabled = True
            bucket.labels = {"env_type": env_type, "substream_id": substream_id}
            # Add a lifecycle rule to limit the bucket to 3 versions
            bucket.add_lifecycle_delete_rule(number_of_newer_versions=int(os.getenv('BUCKET_LIFECYCLE', 3)))
            bucket.patch()
            logging.info(f"Bucket {bucket_name} updated with labels and versioning enabled")
        except TryAgain as e:
            raise TryAgain
        except GoogleAPIError as e:
            if count < MAX_TRIES:
                logging.warning(f"Retrying due to GoogleAPIError updating bucket {bucket_name} in project {etl_project}: {e}")
            else:
                logging.error(f"GoogleAPIError updating bucket {bucket_name} in project {etl_project}: {e}")
            raise e
        except Exception as e:
            if count < MAX_TRIES:
                logging.warning(f"Retrying due to unexpected error updating bucket {bucket_name} in project {etl_project}: {e}")
            else:
                logging.error(f"Unexpected error updating bucket {bucket_name} in project {etl_project}: {e}")
            raise e

    def setup_gcs_bucket(self, bucket_name):
        if os.environ.get('CI'):
            logging.info("Running in CI environment")
            etl_project = os.environ['ETLPROJECT']
            region = self.extract_region_from_labels()
            if not region:
                logging.error("Region not found in labels, exiting.")
                exit(1)
            env_type = os.environ['ENV_TYPE']
            substream_id = os.environ['SUBSTREAM_ID']
            impersonation_svc = os.environ['IMPERSONATE_SVC']
            deployment_cred, _ = google.auth.default()
        else:
            # Local development
            logging.info("Running in local environment")
            etl_project = 'd-ulti-pf-use4-dev-s01-fbe8'
            region = 'us-east4'    
            env_type = 'eng'
            substream_id = '6657dbf8-1f8e-24c3-5515-56a146bd45b3'
            impersonation_svc = 'svc-platform@d-ulti-data-pfplatform-01-721d.iam.gserviceaccount.com'
            deployment_auth = json.loads(open(os.environ['DEPLOYMENT_CREDENTIALS']).read())    
            deployment_cred = service_account.Credentials.from_service_account_info(deployment_auth)

        logging.info(f"Creating GCS bucket {bucket_name}")
        if not self.bucket_exists(bucket_name, etl_project, deployment_cred):
            self.create_gcs_bucket(bucket_name, etl_project, region, deployment_cred)
        self.update_bucket(bucket_name, etl_project, env_type, substream_id, deployment_cred, impersonation_svc)

    def extract_region_from_labels(self):
        labels = os.environ.get('LABELS', '')
        labels_list = labels.split(',')
        for label in labels_list:
            if label.startswith('region='):
                _, region_value = label.split('=')
                return region_value
        return None
        
    def clean_up_gcs_bucket(self, bucket_name, etl_project, root_directory, traverse=False, folder_name='etm', file_extension='.json', include_subfolders=False):
            """
            Compares files in the GCS bucket with the local directory and deletes files that do not exist in the local directory.
            
            Args:
                bucket_name (str): The name of the GCS bucket.
                etl_project (str): The name of the ETL project.
                root_directory (str): The local directory containing the files.
                traverse (bool): Flag to decide whether to traverse directories looking for a designated folder.
                folder_name (str): The name of the folder to look for when traversing directories.
                file_extension (str): The file extension to filter files.
                include_subfolders (bool): Flag to decide whether to include subfolders in the prefix.
            """
            try:
                # Initialize a GCS client with the existing credentials and project
                storage_client = storage.Client(project=etl_project)
                bucket = storage_client.bucket(bucket_name)

                # List all files in the GCS bucket
                blobs = bucket.list_blobs()
                
                # Get the list of file names from the root directory and folder
                files_list = self.get_files_list(root_directory, folder_name, file_extension, traverse, include_subfolders)

                # Create a set of file names from the files_list
                files_set = {file_info['file name'] for file_info in files_list}
                
                # Deleted Files
                deleted_files = []
                
                for blob in blobs:
                    blob_folder_path = os.path.dirname(blob.name)
                    blob_file_name = os.path.basename(blob.name)
                    if blob.name.endswith(file_extension) and blob_file_name not in files_set:
                        logging.info(f"File {blob_file_name} does not exist in the source directory and matches the extension {file_extension}. Deleting from GCS.")
                        blob.delete()
                        deleted_files.append({
                            'GCS File Path': blob_folder_path,
                            'File Name': blob_file_name
                        })
                        logging.info(f"Deleted {blob_file_name} from {bucket_name}")
                    else:
                        logging.info(f"File {blob_file_name} exists in the source directory or does not match the extension {file_extension}. No action needed.")

            except Exception as e:
                logging.error(f"Error comparing and removing files from GCS: {e}")
            
            if deleted_files:
                # Print list of files to GitHub summary
                self.write_table_to_github_summary(deleted_files, f"Files Deleted From GCS Bucket: {bucket_name}")
            else:
                self.write_to_github_summary("No files were deleted from the GCS bucket.")
        
    def upload_files_to_gcs(self, bucket_name, etl_project, root_directory, traverse=False, folder_name='etm', file_extension='.json', include_subfolders=False):
        """
        Copies files that match the file extension associated with the file_extension variable to a Google Cloud Storage bucket.

        Args:
            bucket_name (str): The name of the GCS bucket.
            etl_project (str): The name of the ETL project.
            root_directory (str): The local directory containing the files.
            traverse (bool): Flag to decide whether to traverse directories looking for a designated folder.
            folder_name (str): The name of the folder to look for when traversing directories.
            file_extension (str): The file extension to filter files for upload.
        """
        deployment_cred = self.get_deployment_credentials()

        # Check if the bucket exists
        if not self.bucket_exists(bucket_name, etl_project, deployment_cred):
            logging.error(f"Bucket {bucket_name} does not exist. Ensure the platform deployment was successful. Refer to GHAs of peoplefabric_dataplatform repo")
            return

        # Initialize a GCS client with the existing credentials and project
        try:
            storage_client = storage.Client(project=etl_project, credentials=deployment_cred)
        except Exception as e:
            logging.error(f"Failed to initialize GCS client: {e}")
            return

        local_directory = root_directory
        logging.info(f"Local directory: {local_directory}")

        # Get the list of files to upload
        files_list = self.get_files_list(root_directory, folder_name, file_extension, traverse, include_subfolders)

        uploaded_files = []

        try:
            for file_info in files_list:
                local_file_path = os.path.join(local_directory, file_info['source'])
                blob_name = os.path.join(file_info['destination'], file_info['file name']).replace(os.sep, '/')
                try:
                    blob = storage_client.bucket(bucket_name).blob(blob_name)
                    blob.upload_from_filename(local_file_path)
                    logging.info(f'Uploaded {local_file_path} to {bucket_name}/{blob_name}')
                    uploaded_files.append({
                        'source': file_info['source'],
                        'destination': f'{bucket_name}/{blob_name}',
                        'file name': file_info['file name']
                    })
                except Exception as e:
                    logging.error(f"Failed to upload {local_file_path} to {bucket_name}/{blob_name}: {e}")
        except Exception as e:
            logging.error(f"Error uploading files: {e}")

        if uploaded_files:
            # Print list of files to GitHub summary
            self.write_table_to_github_summary(uploaded_files, f"Files Uploaded to GCS bucket : {bucket_name}")
        else:
            self.write_to_github_summary("No files were uploaded to the GCS bucket.")

    # TODO: main not be needed revise
    def copy_json_files_to_gcs(self, bucket_name, etl_project, schema_dir):
            """
            Copies JSON files to a Google Cloud Storage bucket.
            """
            deployment_cred = self.get_deployment_credentials()

            # Check if the bucket exists
            if not self.bucket_exists(bucket_name, etl_project, deployment_cred):
                logging.error(f"Bucket {bucket_name} does not exist. Ensure the platform deployment was successful. Refer to GHAs of peoplefabric_dataplatform repo")
            else:
                # Initialize a GCS client with the existing credentials and project
                storage_client = storage.Client(project=etl_project, credentials=deployment_cred)

                # Get the bucket
                bucket = storage_client.bucket(bucket_name)

                local_directory = schema_dir
                logging.info(f"local directory: {local_directory}")

                try:  
                    # List all JSON files in the local directory
                    for root, _, files in os.walk(local_directory):
                        for file_name in files:
                            if file_name.endswith('.json'):
                                local_file_path = os.path.join(root, file_name)
                                blob = bucket.blob(file_name)
                                # Upload the file and overwrite if it already exists
                                blob.upload_from_filename(local_file_path)
                                logging.info(f'Uploaded {local_file_path} to {bucket_name}/{file_name}')     
                            else:
                                logging.warning(f'{file_name} is not json')       
                except Exception as e:
                    logging.error(f"Error uploading files: {e}")

    
    def artifact_registry_repo_exists(self, etl_project, location, repository_id, deployment_cred, impersonation_svc):
        """
        Checks if an artifact repository exists in Google Artifact Registry.

        Args:
            etl_project (str): The ID of the Google Cloud project.
            location (str): The location where the repository will be created (e.g., 'us-central1').
            repository_id (str): The ID of the repository to be checked.
            deployment_cred (object): The deployment credentials.
            impersonation_svc (str): The service account to impersonate.

        Returns:
            bool: True if the repository exists, False otherwise.
        """
        try:
            client = artifactregistry_v1.ArtifactRegistryClient(credentials=self.impersonate_service_account(deployment_cred, impersonation_svc))
            parent = f"projects/{etl_project}/locations/{location}"
            repo_name = f"{parent}/repositories/{repository_id}"
            client.get_repository(name=repo_name)
            logging.info(f"Repository {repository_id} already exists in {location}")
            return True
        except NotFound:
            return False
        except GoogleAPIError as e:
            logging.error(f"Error checking if repository {repository_id} exists in {location}: {e}")
            raise e

    @retry(
        retry=(retry_if_exception_type()),
        stop=stop_after_attempt(MAX_TRIES),
        wait=wait_fixed(BACK_OFF_TIME),
        reraise=True
    )
    def create_artifact_registry_repo(self, etl_project, location='us', repository_id='data-extraction', repository_format='DOCKER'):
        """
        Creates a repository in Google Artifact Registry.

        Args:
            etl_project (str): The ID of the Google Cloud project.
            location (str): The location where the repository will be created (e.g., 'us-central1').
            repository_id (str): The ID of the repository to be created.
            repository_format (str): The format of the repository (e.g., 'DOCKER', 'MAVEN', 'NPM'). Default is 'DOCKER'.

        Returns:
            None
        """
        try:
            count = self.create_artifact_registry_repo.retry.statistics.get("attempt_number") or self.create_artifact_registry_repo.statistics.get("attempt_number")
            deployment_cred = self.get_deployment_credentials()
            impersonation_svc = os.environ['IMPERSONATE_SVC']
            
            # Check if the repository already exists
            if self.artifact_registry_repo_exists(etl_project, location, repository_id, deployment_cred, impersonation_svc):
                logging.info(f"Repository {repository_id} already exists in {location}. Skipping creation.")
                return
            
            # Initialize the Artifact Registry client
            client = artifactregistry_v1.ArtifactRegistryClient(credentials=self.impersonate_service_account(deployment_cred, impersonation_svc))

            # Define the parent resource
            parent = f"projects/{etl_project}/locations/{location}"

            # Define the repository
            repository = artifactregistry_v1.Repository(
                format=artifactregistry_v1.Repository.Format[repository_format]
            )

            # Create the repository
            operation = client.create_repository(
                request={
                    "parent": parent,
                    "repository_id": repository_id,
                    "repository": repository
                }
            )

            # Wait for the operation to complete
            response = operation.result()

            logging.info(f"Repository {repository_id} created in {location} with format {repository_format}")
        except TryAgain as e:
            raise TryAgain
        except GoogleAPIError as e:
            if count < MAX_TRIES:
                logging.warning(f"Retrying due to GoogleAPIError creating repository {repository_id} in {location}: {e}")
            else:
                logging.error(f"GoogleAPIError creating repository {repository_id} in {location}: {e}")
            raise e
        except Exception as e:
            if count < MAX_TRIES:
                logging.warning(f"Retrying due to error creating repository {repository_id} in {location}: {e}")
            else:
                logging.error(f"Error creating repository {repository_id} in {location}: {e}")
            raise e
        
    # Filter and sort jobs by job name suffix and creation time
    def filter_and_sort_jobs(self, jobs, job_name, suffix):
        '''
        Filters and sorts jobs by job name suffix and creation time desc.
        args:
            jobs (list): The list of jobs.
            job_name (str): The job name.
            suffix (str): The job name suffix.
        '''
        filtered_jobs = [job for job in jobs if f'{job_name}-{suffix}' in job['name']]
        sorted_jobs = sorted(filtered_jobs, key=lambda x: x['createTime'], reverse=True)
        return sorted_jobs
    
    def get_df_job_name(self, projectId, region, workspace, job_name, update_job, parallel_job, job_name_override, tf_operation='apply'):
        """
        Returns the Dataflow job name.
        args:
            projectId (str): The project ID.
            region (str): The region.
            workspace (str): The workspace (alt-config)
            job_name (str): The job name.
            update_job (str): The update job flag.
            parallel_job (str): The parallel job flag   
            job_name_override (str): The job name override.
            tf_operation (str): The Terraform operation. To be used during job name override.         
        """
        # Set the workspace to lower case and strip any leading/trailing whitespace
        # Set the parallel job flag to lower case and strip any leading/trailing whitespace
        # Set the parallel pipeline workspace to the workspace with a 1 appended to it
        workspace = 'default' if workspace.lower().strip() == 'dev' else workspace.lower().strip()
        update_job = update_job.lower().strip()
        parallel_job = parallel_job.lower().strip()
        # parallel_pipeline_workspace = f"{workspace}1"
        
        job = DataflowJob(
            project_id=projectId,
            region=region,
            job_name=job_name,
            workspace=workspace,
            is_parallel=True if parallel_job == 'true' else False,
            is_update=True if update_job == 'true' else False
        )

        try:
            self.credentials = None
            self.setup_auth()
            df_service = build('dataflow', 'v1b3', credentials=self.credentials, cache_discovery=False)
            request = df_service.projects().locations().jobs().list(
                projectId=projectId,
                location=region,
                filter=f'ACTIVE'
            )
            response = request.execute()
            jobs = response.get('jobs')
            sorted_jobs = self.filter_and_sort_jobs(jobs, job_name, workspace)

            if job_name_override:
                job_name_override.strip()
                if not sorted_jobs:
                    logging.info("No existing jobs found")
                    job.targeted_job_name = job.remove_envtype_suffix(job_name_override)
                else:
                    # split the job name override by hyphen
                    jno_split = job_name_override.split('-')
                    jno_workspace = jno_split[3] #Ex. df-pfab-strm-default-a-eng
                    jno_deployment_type = jno_split[4]
                    logging.info(f"Override job name workspace: {jno_workspace} and deployment type: {jno_deployment_type}")
                    if workspace not in jno_workspace:
                        logging.error(f"Job name override workspace: {job_name_override} does not match the selected workspace: {workspace}. Please provide a valid job name override.")
                        exit(1)              
                    if jno_deployment_type != 'a' and jno_deployment_type != 'b':
                        logging.error(f"Job name override {job_name_override} does not contain 'a' or 'b' suffix. Please provide a valid job name override.")
                        exit(1)              
                    job.targeted_job_name = job_name_override
                    job.set_job_details_from_targeted_job()
                    if tf_operation == 'destroy':
                        logging.info(f"Deployment is type Destroy. Updating target job name")
                        job.targeted_job_name = job.previous_job_name

                logging.info(f"Job name override is set to {job_name_override}. Deployment will use the following: {job.targeted_job_name}")            
                logging.info(f"Targeting Deployment Job: {job.targeted_job_name}")
                logging.info(f"Previous Deployment Job to Destroy: {job.previous_job_name}")
                return job.targeted_job_name, job.previous_job_name                

            # Filter job based on workspace only to figure out if it's in the pp workspace indicated by (workspace1)
            else:              
                if sorted_jobs:
                    logging.info(f"Initial sorted Jobs: {sorted_jobs}")
                    job.targeted_job_name = sorted_jobs[0]['name']
                    job.set_job_details_from_targeted_job()
                else:
                    logging.info("No existing jobs found")
                    job.targeted_job_name = ""
                    job.set_job_details_from_targeted_job()
                
                logging.info(f"Targeting Deployment Job: {job.targeted_job_name}")
                logging.info(f"Previous Deployment Job to Destroy: {job.previous_job_name}")
                return job.targeted_job_name, job.previous_job_name
        except Exception as e:
            logging.error(f"Error setting new job name: {e}")
            return None, None
        
def main():
    logging.basicConfig(level=logging.INFO)
    fire.Fire(GHAGCPUtils)

if __name__ == "__main__":
    main()
