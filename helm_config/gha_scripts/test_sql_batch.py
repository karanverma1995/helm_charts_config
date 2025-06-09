import os
import os.path
import google.auth
import googleapiclient.discovery
import logging
import fire
import time
import importlib
import xml.etree.ElementTree as ET
from omni_commons import DatasetManager, TableViewManager
from omni_commons.PubSubManager import PubSubManager
from google.cloud import bigquery
from google.auth.transport.requests import AuthorizedSession
from gha.gha_environment_setup import EnvironmentSetup
from gha.gha_workflow_steps import GHA
from gha.resources.systemTestObjects import systemTestObjects

logging.basicConfig(level=logging.INFO)
logging.info("Starting automation functions")


class GHASQLBatchTests(GHA):
    """
    A class that represents helps setup infrastructure for SQL Batch system steps for GitHub Actions workflow.
    """

    def __init__(self, init=True, project_id=None, impersonation_svc=None):
        """
        Initializes the GHASQLBatchTests object.

        Args:
            init (bool): Whether to initialize the object.
            project_id (str): The ID of the GCP project.
            impersonation_svc (str): The service account to impersonate.
        """
        if init:
            super().__init__()
            self.deployment_cred, self.pid = google.auth.default()
            self.impersonation_auth = None
            if project_id is None:
                self.project_id = os.getenv('ETLPROJECT')
            else:
                self.project_id = project_id
            if impersonation_svc:
                self.impersonation_auth = AuthorizedSession(self.impersonate_service_account(self.deployment_cred, impersonation_svc))
                self.bq_client = bigquery.Client(project=self.project_id, credentials=self.impersonation_auth.credentials)
            else:
                self.bq_client = bigquery.Client(project=self.project_id, credentials=self.deployment_cred)
            self.dataset_manager = DatasetManager(project=self.project_id, bigquery_client=self.bq_client)
            self.table_view_manager = TableViewManager(bigquery_client=self.bq_client, project=self.project_id)
            self.pubsub_manager = PubSubManager(self.project_id)
            self.df_service_client = googleapiclient.discovery.build('dataflow',
                                                    'v1b3',
                                                    credentials=self.deployment_cred,
                                                    cache_discovery=False
                                                    )
            self.system_test_objects = systemTestObjects()
            self.location = os.getenv('LOCATION', 'US')
            self.env_type = os.getenv('ENV_TYPE', 'eng')
            self.substream_id = os.getenv('SUBSTREAM_ID', '6657dbf8-1f8e-24c3-5515-56a146bd45b3')
            self.env_impersonation_svc = impersonation_svc

    def get_java_version(self):
        """
        Extracts the Java version from the .jabbarc file and sets it as an output.

        Raises:
            Exception: If unable to set the Java version.
        """
        try:
            logging.info("Extracting java version from jabbarc")
            with open("../../.jabbarc") as f:
                fline = f.readline().rstrip()
                logging.info(f"Java Version: {fline}")
                print(f"::set-output name=JAVA_VERSION::{fline}")
        except Exception as e:
            logging.error(f"Unable to set java version: {e}")
            raise e

    def create_bq_dataset(self, dataset_name, location, env_type, substream_id):
        """
        Creates a BigQuery dataset.

        Args:
            dataset_name (str): The name of the dataset.
            location (str): The location of the dataset.
            env_type (str): The environment type.
            substream_id (str): The substream ID.

        Raises:
            Exception: If there is an error in creating the dataset object.
        """
        logging.info(f"Creating Dataset: {dataset_name} in GCP Project: {self.project_id}")
        try:
            request = {
                "datasetId": dataset_name,
                "location": location,
                "defaultTableExpirationMs": 604800000,
                "labels": {"env_type": env_type, "substream_id": substream_id}
            }
            self.dataset_manager.create_or_update_dataset(request)
        except Exception as e:
            logging.error(f"Error in creating dataset object: {e}")
            raise e

    def delete_bq_dataset(self, dataset_names):
        """
        Deletes BigQuery datasets.

        Args:
            dataset_names (list): The names of the datasets to delete.

        Raises:
            Exception: If there is an error in deleting the dataset object.
        """
        logging.info(f"Deleting Datasets: {dataset_names} in GCP Project: {self.project_id}")
        try:
            self.dataset_manager.delete_datasets(dataset_names, True)
        except Exception as e:
            logging.error(f"Error in deleting dataset object: {e}")
            raise e

    def create_bq_table(self, table_name, dataset_name, table_schema, clustering_fields, description, env_type, substream_id):
        """
        Creates a BigQuery table.

        Args:
            table_name (str): The name of the table.
            dataset_name (str): The name of the dataset.
            table_schema (dict): The schema of the table.
            clustering_fields (list): The clustering fields of the table.
            description (str): The description of the table.
            env_type (str): The environment type.
            substream_id (str): The substream ID.

        Raises:
            Exception: If there is an error in creating the table.
        """
        logging.info(f"Creating Table: {table_name} in Dataset: {dataset_name} in GCP Project: {self.project_id}")
        try:
            config = {
                "tableID": table_name,
                "clustering": clustering_fields,
                "datasetName": dataset_name,
                "description": description,
                "schema": table_schema,
                "timePartitioning": bigquery.TimePartitioning(
                    type_=bigquery.TimePartitioningType.DAY,
                    expiration_ms=2592000,
                ),
                "labels": {"env_type": env_type, "substream_id": substream_id}
            }
            logging.info(f"The table config: {config}")
            self.table_view_manager.create_or_update_table_with_config(config)
        except Exception as e:
            logging.error(f"Error in creating table: {e}")
            raise e

    def delete_bq_table(self, table_name, dataset_name):
        """
        Deletes a BigQuery table.

        Args:
            table_name (str): The name of the table.
            dataset_name (str): The name of the dataset.

        Raises:
            Exception: If there is an error in deleting the table.
        """
        logging.info(f"Deleting Table: {table_name} in Dataset: {dataset_name} in GCP Project: {self.project_id}")
        try:
            self.table_view_manager.delete_tables_with_substring(table_name, True, dataset_name)
        except Exception as e:
            logging.error(f"Error in deleting table: {e}")
            raise e

    def deploy_pubsub_objects(self, topic_name, env_type, substream_id, subscription_name=None):
        """
        Deploys PubSub objects.

        Args:
            topic_name (str): The name of the topic.
            env_type (str): The environment type.
            substream_id (str): The substream ID.
            subscription_name (str): The name of the subscription.

        Raises:
            Exception: If there is an error in creating the PubSub objects.
        """
        logging.info(f"Creating PubSub Objects in GCP Project: {self.project_id}")
        try:
            if topic_name is not None:
                logging.info(f"Creating Topic: {topic_name}")
                self.pubsub_manager.create_topic(topic_name)
                logging.info(f"Adding labels to Topic: {topic_name}")
                labels = {"env_type": env_type, "substream_id": substream_id}
                self.pubsub_manager.update_topic(topic_name, labels)
            if subscription_name is not None:
                logging.info(f"Creating PubSub Subscription: {subscription_name}")
                self.pubsub_manager.create_subscription(topic_name, subscription_name)
                logging.info(f"Adding labels to Subscription: {subscription_name}")
                self.pubsub_manager.update_subscription(subscription_name, labels)
            logging.info(f"PubSub Topic and Subscriptions created successfully")
        except Exception as e:
            logging.error(f"Issues creating PubSub Object: {e}")
            raise e

    def delete_pubsub_objects(self, topic_name, subscription_name=None):
        """
        Deletes PubSub objects.

        Args:
            topic_name (str): The name of the topic.
            subscription_name (str): The name of the subscription.

        Raises:
            Exception: If there is an error in deleting the PubSub objects.
        """
        logging.info(f"Deleting PubSub Objects in GCP Project: {self.project_id}")
        try:
            if subscription_name is not None:
                logging.info(f"Deleting Subscription: {subscription_name}")
                self.pubsub_manager.delete_subscription(subscription_name)
            if topic_name is not None:
                logging.info(f"Deleting Topic: {topic_name}")
                self.pubsub_manager.delete_topic(topic_name)
            logging.info(f"PubSub Topic and Subscriptions were deleted successfully")
        except Exception as e:
            logging.error(f"Error in deleting PubSub Objects: {e}")
            raise e

    def get_dataflow_job_id(self, project, region, job_name, creation_time):
        """
        Gets the Dataflow job ID.

        Args:
            project (str): The ID of the GCP project.
            region (str): The region of the Dataflow job.
            job_name (str): The name of the Dataflow job.
            creation_time (str): The creation time of the Dataflow job.

        Returns:
            str: The ID of the Dataflow job, if found. Otherwise, None.
        """
        job_id = None
        job_name = job_name.lower()
        try:
            logging.info(f"Fetching job id for job named {job_name} and created on {creation_time}")
            request = self.df_service_client.projects().locations().jobs().list(projectId=project, location=region)
            response = request.execute()
            jobs = response.get('jobs', [])
            for job in jobs:
                if 'name' in job.keys() and 'createTime' in job.keys():
                    if job['name'] == job_name and job['createTime'] >= creation_time:
                        job_id = job['id']
                        logging.info(f"Job ID: {job_id} was found for Job Name: {job_name} and Creation Time: {creation_time}")
                        return job_id
        except Exception as e:
            logging.error(f"Unable to get dataflow job id for job {job_name}: {e}")
            raise e
        return job_id

    def check_dataflow_job_status(self, project, region, job_id):
        """
        Checks the status of a Dataflow job.

        Args:
            project (str): The ID of the GCP project.
            region (str): The region of the Dataflow job.
            job_id (str): The ID of the Dataflow job.

        Returns:
            str: The status of the Dataflow job, if found. Otherwise, None.
        """
        job_status = None
        try:
            logging.info(f"Getting job status for job {job_id}")
            request = self.df_service_client.projects().locations().jobs().get(projectId=project, location=region, jobId=job_id, view='JOB_VIEW_SUMMARY')
            response = request.execute()
            if 'currentState' in response.keys():
                if response['currentState'] == 'JOB_STATE_CANCELLED':
                    job_status = "CANCELLED"
                elif response['currentState'] == 'JOB_STATE_CANCELLING':
                    job_status = "CANCELLING"
                elif response['currentState'] == 'JOB_STATE_DONE':
                    job_status = "DONE"
                elif response['currentState'] == 'JOB_STATE_DRAINED':
                    job_status = "DRAINED"
                elif response['currentState'] == 'JOB_STATE_DRAINING':
                    job_status = "DRAINING"
                elif response['currentState'] == 'JOB_STATE_FAILED':
                    job_status = "FAILED"
                elif response['currentState'] == 'JOB_STATE_PENDING':
                    job_status = "PENDING"
                elif response['currentState'] == 'JOB_STATE_QUEUED':
                    job_status = "QUEUED"
                elif response['currentState'] == 'JOB_STATE_RESOURCE_CLEANING_UP':
                    job_status = "RESOURCE CLEANING UP"
                elif response['currentState'] == 'JOB_STATE_RUNNING':
                    job_status = "RUNNING"
                elif response['currentState'] == 'JOB_STATE_STOPPED':
                    job_status = "STOPPED"
                elif response['currentState'] == 'JOB_STATE_UNKNOWN':
                    job_status = "UNKNOWN"
                elif response['currentState'] == 'JOB_STATE_UPDATED':
                    job_status = "UPDATED"
                else:
                    job_status = "UNKNOWN"
        except Exception as e:
            logging.error(f"Error in getting job status for job  {job_id}: {e}")
            raise e
        return job_status

    def check_dataflow_job_started(self, project, region, job_name, creation_time):
        """
        Checks if a Dataflow job has started running.

        Args:
            project (str): The ID of the GCP project.
            region (str): The region of the Dataflow job.
            job_name (str): The name of the Dataflow job.
            creation_time (str): The creation time of the Dataflow job.

        Raises:
            Exception: If there is an error in checking the status of the Dataflow job.
        """
        try:
            dataflow_job_id = self.get_dataflow_job_id(project, region, job_name, creation_time)
            job_status = ""
            job_name = job_name.lower()
            while (job_status != "RUNNING"):
                job_status = self.check_dataflow_job_status(project=project,region=region,job_id=dataflow_job_id)
                logging.info(f"Dataflow job {job_name} is in state {job_status}")
                if job_status == "FAILED":
                    raise Exception(f"Dataflow job {job_name} failed")
                elif job_status == "CANCELLED":
                    raise Exception(f"Dataflow job {job_name} has been cancelled")
                elif job_status is None:
                    break
                time.sleep(10)
        except Exception as e:
            logging.error("Error in checking status of dataflow job: {e}")
            raise e

    def cancel_dataflow_job(self, project, region, job_name, creation_time):
        """
        Cancels a Dataflow job.

        Args:
            project (str): The ID of the GCP project.
            region (str): The region of the Dataflow job.
            job_name (str): The name of the Dataflow job.
            creation_time (str): The creation time of the Dataflow job.

        Raises:
            Exception: If there is an error in cancelling the Dataflow job.
        """
        job_status = ""
        job_name = job_name.lower()
        try:
            dataflow_job_id = self.get_dataflow_job_id(project, region, job_name, creation_time)
            job_status = self.check_dataflow_job_status(project=project,region=region,job_id=dataflow_job_id)
            while (job_status in ["RUNNING", "CANCELLING"]):
                if job_status == "RUNNING":
                    request_body = {
                        'requestedState': 'JOB_STATE_CANCELLED'
                    }
                    request = self.df_service_client.projects().locations().jobs().update(projectId=project, location=region, jobId=dataflow_job_id, body = request_body)
                    response = request.execute()
                    logging.info(f'Cancel response: {response}')
                elif job_status == "FAILED":
                    raise Exception(f"Dataflow job {job_name} failed")
                elif job_status == "CANCELLED":
                    raise Exception(f"Dataflow job {job_name} has been cancelled")
                job_status = self.check_dataflow_job_status(project=project,region=region,job_id=dataflow_job_id)
                logging.info(f"Dataflow job {job_name} is in state {job_status}")
                time.sleep(10)

            logging.info(f"Dataflow job {job_name} has been cancelled")
        except Exception as e:
            logging.error("Error in checking status of dataflow job: {e}")
            raise e

    def aggregate_xml_files(self, report_directory, outputfile_name):
        """
        Aggregates multiple JUnit test reports into a single XML file.

        Parameters:
        - report_directory (str): Path to the directory containing the JUnit XML files.
        - outputfile_name (str): Name of the output aggregated XML file.
        """
        try:
            report_path = os.path.join(report_directory, outputfile_name)
            if os.path.exists(report_path):
                os.remove(report_path)
            with open(report_path, 'a') as outfile:
                outfile.write("<testsuites>\n")

                # List all XML files in the given directory
                for file_name in os.listdir(report_directory):
                    if file_name != outputfile_name and file_name.endswith('.xml'):
                        file_path = os.path.join(report_directory, file_name)

                        # Parse the XML file
                        tree = ET.parse(file_path)
                        root = tree.getroot()
                        # Extract and write <testsuite> elements
                        if root.tag == 'testsuite':
                            testsuite_str = ET.tostring(root, encoding='unicode')
                            outfile.write(testsuite_str + "\n")
                        else:
                            for element in root:
                                if element.tag == 'testsuite':
                                    testsuite_str = ET.tostring(element, encoding='unicode')
                                    outfile.write(testsuite_str + "\n")

                # Close the root element
                outfile.write("</testsuites>\n")
        except Exception as e:
            logging.error(f"Error aggregating xml data into one file: {e}")
            raise e
    
    def setup_test_objects(self):
        """
        Sets up the test objects for the SQL Batch system.
        """
        try:
            logging.info("Setting up test objects for SQL Batch System Tests")
            # Create BigQuery Metadata Dataset
            self.create_bq_dataset(self.system_test_objects.metadata_dataset, 
                                   self.location, 
                                   self.env_type, 
                                   self.substream_id
                                   )
            # Create Ingestion Results Table
            self.create_bq_table(self.system_test_objects.bq_table_name, 
                                 self.system_test_objects.metadata_dataset, 
                                 self.system_test_objects.ingestion_results_schema, 
                                 self.system_test_objects.ingestion_clustering_fields, 
                                 self.system_test_objects.bq_table_description, 
                                 self.env_type, 
                                 self.substream_id
                                 )
            # Create Tenant Specific BQ Datasets
            for dataset in self.system_test_objects.bq_datasets:
                self.create_bq_dataset(dataset, 
                                       self.location, 
                                       self.env_type, 
                                       self.substream_id
                                       )

            # Create PubSub Topics and Subscriptions
            for topic, subscription in self.system_test_objects.topic_subscription_mapping.items():
                if subscription is None:
                    self.deploy_pubsub_objects(self.system_test_objects.topics[topic], 
                                               self.env_type, 
                                               self.substream_id
                                               )
                else:
                    self.deploy_pubsub_objects(self.system_test_objects.topics[topic], 
                                               self.env_type, 
                                               self.substream_id, 
                                               self.system_test_objects.subscriptions[subscription])
        except Exception as e:
            logging.error(f"Error in setting up test objects: {e}")
    
    def tear_down_test_objects(self):
        """
        Tears down the test objects for the SQL Batch system.
        """
        try:
            logging.info("Tearing down test objects for SQL Batch System Tests")

            # Delete PubSub Topics and Subscriptions
            for topic, subscription in self.system_test_objects.topic_subscription_mapping.items():
                if subscription is None:
                    self.delete_pubsub_objects(self.system_test_objects.topics[topic])
                else:
                    self.delete_pubsub_objects(self.system_test_objects.topics[topic], 
                                               self.system_test_objects.subscriptions[subscription]
                                               )
            
            # Delete BigQuery Metadata Dataset
            self.delete_bq_dataset([self.system_test_objects.metadata_dataset])
            # Delete Tenant Specific BQ Datasets
            for dataset in self.system_test_objects.bq_datasets:
                self.delete_bq_dataset([dataset])

        except Exception as e:
            logging.error(f"Error in tearing down test objects: {e}")
            raise e
    
    def set_test_environment_variables(self):
        for topic, subscription in self.system_test_objects.topic_subscription_mapping.items():
            if subscription is None:
                self.env_setup.modify_GHA_environment(topic, self.system_test_objects.topics[topic])
            else:
                self.env_setup.modify_GHA_environment(topic, self.system_test_objects.topics[topic])
                self.env_setup.modify_GHA_environment(subscription, self.system_test_objects.subscriptions[subscription])
        
        self.env_setup.modify_GHA_environment("IMAGE_TAG", self.system_test_objects.image_tag)

def main():
    fire.Fire(GHASQLBatchTests)

if __name__ == "__main__":
    main()
