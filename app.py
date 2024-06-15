#!/usr/bin/env python3

from aws_cdk import App, Environment, Tags

from stacks.cross_account_deploy_pipeline import CrossAccountDeployPipelines
from stacks.data import load_parameters
from stacks.stages import DeployStage
from stacks.stages_ad import DeployStageAD
from stacks.stages_pipeline import DeployStagePipeline


PROJECT_NAME = "ecs-demo"
APP_NAME = "app-deployment"

app = App()
param = load_parameters()


for region in param.get("regions"):
    pipeline_env = Environment(
        account=region["accountId"],
        region=region["region"],
    )
    pipelines = CrossAccountDeployPipelines(
        app,
        project_name=PROJECT_NAME,
        app_name=APP_NAME,
        pipeline_env=pipeline_env,
        pipeline_region_name_override=region["region"],

    )

    for environment, account in param.get("accounts").items():

        deploy_env = Environment(
            account=region["accountId"], region=region["region"])

        if (environment=="repository-account"):
            deploy_stage_ad = DeployStageAD(
                app,
                f"""{environment}-{region["region"]}""",
                environment=environment,
                region=region["region"],
                env=deploy_env,
            )
            pipelines.add_target_environment(
                environment, deploy_stages=[deploy_stage_ad])
        elif (environment=="pipeline-account"):
            deploy_stage_pipeline = DeployStagePipeline(
                app,
                f"""{environment}-{region["region"]}""",
                environment=environment,
                region=region["region"],
                app_config=param.get("appConfig", {}),
                webhook_url_slack = param.get("webhookUrlSlack"),
                env=deploy_env,
            )
            pipelines.add_target_environment(
                environment, deploy_stages=[deploy_stage_pipeline])
        else:
            deploy_stage = DeployStage(
                app,
                f"""{environment}-{region["region"]}""",
                environment=environment,
                region=region["region"],
                app_config=param.get("appConfig", {}),
                env=deploy_env,
                cidr=account["cidr"],
                ecr_repository=""
            )

        
            pipelines.add_target_environment(
                environment, deploy_stages=[deploy_stage])

        Tags.of(app).add("environment", environment)
        Tags.of(app).add("Environment", environment)
        Tags.of(app).add("system", PROJECT_NAME)
app.synth()
