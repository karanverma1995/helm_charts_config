# ===========================================================
# COPYRIGHT 2017 MIDSHIPS
# Do not distribute without permission and this
# file is only usable with a valid license.

# Docker file to build ForgeRock Access Management Image.

# For more information visit www.midships.io

# Image recommended name: forgerock-am
# ===========================================================

ARG IMAGE_TAG="latest"
ARG IMAGE_SRC="gcr.io/gcp-keng01/kronos-authn-tomcat-base-@BRANCH@"
FROM ${IMAGE_SRC}:${IMAGE_TAG}

# Arguments
# ---------
# Defaults:
ARG cloud_type="GCP"
ARG am_version=@OPENAMEXT_WAR_VERSION@
ARG amster_version=@AMSTER_VERSION@
ARG config_upgrader_version=@CONFIG_UPGRADER_VERSION@
ARG openam_version=@OPENAM_VERSION@
ARG ssotools_version=@SSOTOOLS_VERSION@
ARG am_uri=openam
ARG am_home=/apps/${am_uri}
ARG path_tmp=/tmp/${am_uri}
ARG filename_am=kronos-openamv720-custom-war
ARG filename_amster=Amster-${amster_version}.zip
ARG filename_ssoadm=AM-SSOAdminTools-${ssotools_version}.zip
ARG ds_version=@DS_VERSION@
ARG filename_ds=DS-${ds_version}.zip
ARG artifactory_base_url=@ARTIFACTORY_URL@
ARG tp_artifact_name=tenantProvisioning
ARG tp_artifact_version=@TPA_VERSION@
ARG authn_patcher_tool_name=authn-patcher-openam-app
ARG authn_patcher_version=@AUTHN_PATCHER_VERSION@
ARG custom_value_artifact_version=9.0.0.15
ARG edb_util_artifact_name=edb-jdbc
ARG edb_util_artifact_version=42.7.3.2
ARG keystore_file=@KEYSTORE_FILENAME@
ARG secret_store_file=@SECRET_STORE_FILENAME@
ARG filename_config_upgrader=Config-Upgrader-${config_upgrader_version}.zip
# Environment Variables
# ---------------------
ENV AM_HOME=${am_home} \
    AM_URI=${am_uri} \
	  UKG_KEYS=${am_home}/authn

# Copy over configuration scripts
# ------------------------------
COPY files/forgerock-am-shared-functionsGHA.sh ${AM_HOME}/scripts/
COPY files/gha_deploy.sh ${AM_HOME}/scripts/
COPY files/rightscale_deploy.sh ${AM_HOME}/scripts/
COPY files/replacePlaceHoldersGHA.sh ${AM_HOME}/scripts/
COPY files/replaceStackCredPlaceHoldersGHA.sh ${AM_HOME}/scripts/
COPY files/userServiceOpenAMGHA.sh ${AM_HOME}/scripts/
COPY files/forgerock-am-shared-functions.sh ${AM_HOME}/scripts/
COPY files/init.sh ${AM_HOME}/scripts/
COPY files/ssoadm.sh ${AM_HOME}/scripts/
COPY files/setup.sh ${path_tmp}/
COPY files/ssoadm_bin.sh ${AM_HOME}/scripts/
COPY files/tomcat-conf ${path_tmp}/tomcat-conf
COPY files/properties ${path_tmp}/properties
COPY files/remote-debug.sh ${AM_HOME}/scripts/
COPY files/userServiceOpenAM.sh ${AM_HOME}/scripts/
COPY files/replacePlaceHolders.sh ${AM_HOME}/scripts/
COPY files/replaceStackCredPlaceHolders.sh ${AM_HOME}/scripts/
COPY files/retrofit_script.sh ${AM_HOME}/scripts/
COPY files/retrofit_script_rollback.sh ${AM_HOME}/scripts/
COPY files/sop_openam_log_collection.sh ${AM_HOME}/scripts/
COPY files/sop_openam_log_collection.sh ${AM_HOME}/scripts/
COPY files/template_boot.json ${AM_HOME}/scripts/
COPY files/rest-api-csrf.json ${AM_HOME}/scripts/
COPY files/email-attrs.json ${AM_HOME}/scripts/
COPY files/uss-attrs.json ${AM_HOME}/scripts/
COPY files/default-secret-store.json ${AM_HOME}/scripts/
COPY files/default-passwords-store.json ${AM_HOME}/scripts/
COPY files/default-keystore.json ${AM_HOME}/scripts/
COPY files/retrofit_script.sh ${AM_HOME}/scripts/
COPY files/retrofit_script_rollback.sh ${AM_HOME}/scripts/
COPY files/updateSampleConfig.sh ${AM_HOME}/scripts/
COPY files/upgradeGeneratedScripts.sh ${AM_HOME}/scripts/
COPY files/healthcheck_script.sh ${AM_HOME}/scripts/
COPY files/cpu_memory_cron.sh ${AM_HOME}/scripts/
COPY files/deployment_info.sh ${AM_HOME}/scripts/
COPY files/logrotate_oam /etc/logrotate.d/

###include_recipe "CREATE_VERSION_SS"
@CREATE_VERSION_SS@

# Setting up the image
# --------------------
RUN chmod u+x ${path_tmp}/*
RUN chmod u+x ${AM_HOME}/scripts/retrofit_script.sh
RUN chmod u+x ${AM_HOME}/scripts/userServiceOpenAM.sh
RUN chmod u+x ${AM_HOME}/scripts/userServiceOpenAMGHA.sh
RUN chmod u+x ${AM_HOME}/scripts/retrofit_script_rollback.sh
RUN chmod u+x ${AM_HOME}/scripts/sop_openam_log_collection.sh
RUN chmod u+x ${AM_HOME}/scripts/updateSampleConfig.sh
RUN chmod u+x ${AM_HOME}/scripts/healthcheck_script.sh
RUN chmod u+x ${AM_HOME}/scripts/upgradeGeneratedScripts.sh
RUN chmod 777 /etc/environment
RUN ${path_tmp}/setup.sh


USER authnuser

EXPOSE 8443 443
RUN chmod +x /apps/openam/scripts/gha_deploy.sh /apps/openam/scripts/rightscale_deploy.sh
ENTRYPOINT ["bash", "/apps/openam/scripts/init.sh"]
