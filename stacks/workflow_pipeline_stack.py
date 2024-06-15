from aws_cdk import (
    Environment,
    Stack,
    CfnOutput,
    Fn,
    Arn,
    ArnComponents,
    aws_ecs as ecs,
    custom_resources as custom,
    aws_codecommit as codecommit,
    aws_codebuild as codebuild,
    aws_lambda as lambdaFunc,
    aws_iam as iam,
    aws_codedeploy as codedeploy,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_elasticloadbalancingv2 as elb,
    aws_ecr as ecr,
    aws_ec2 as ec2,
    aws_sns as sns,
    
)
import yaml
from constructs import Construct
from typing import Dict, Mapping, Any
from utils.constants import Constants
from utils.functions_common import create_resource_name

default_http_port = Constants.DEFAULT_HTTP_PORT
default_https_port = Constants.DEFAULT_HTTPS_PORT


class workflowPipelineStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env: Environment,
        app_config,
        webhook_url_slack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, env=env, **kwargs)

        # Load buildspec file for codebuild
        def load_buildspec(stage):
            with open(f"data/app-sources/buildspec_{stage}.yaml", "r") as f:
                build_spec = f.read()
                return yaml.safe_load(build_spec)

        # Creates new pipeline artifacts
        source_artifact = codepipeline.Artifact("SourceArtifact")
        build_image_artifact = codepipeline.Artifact("BuildImageArtifact")
        build_build_artifact = codepipeline.Artifact("BuildBuildArtifact")
        build_unittest_artifact = codepipeline.Artifact("BuildUnittestArtifact")
        build_code_analysis_artifact = codepipeline.Artifact("BuildCodeAnalysisArtifact")
        build_intergration_artifact = codepipeline.Artifact("BuildIntergrationArtifact")
        build_loadtest_artifact = codepipeline.Artifact("BuildLoadTestArtifact")
        self.deployment_groups = []

        build_image_spec = load_buildspec("build_image")
        build_build_spec = load_buildspec("build")
        build_code_analysis_spec = load_buildspec("code_analysis")
        build_intergration_spec = load_buildspec("intergration")
        build_load_test_spec = load_buildspec("load_test")
        build_unittest_spec = load_buildspec("unittest")


        # Get codecommit repository
        code_repository = codecommit.Repository.from_repository_name(self, f"""{app_config["repository"]}Repo""",
                                                                    repository_name=app_config["repository"]
                                                                    )

        # CodeBuild project that builds
        build_build = codebuild.Project(
            self, "Build-build",
            build_spec=codebuild.BuildSpec.from_object_to_yaml(build_build_spec),
            source=codebuild.Source.code_commit(
                repository=code_repository,
                branch_or_ref=app_config["branch"],
            )
        )

        # CodeBuild project that builds unittest
        build_unittest = codebuild.Project(
            self, "Build-unittest",
            build_spec=codebuild.BuildSpec.from_object_to_yaml(build_unittest_spec),
            source=codebuild.Source.code_commit(
                repository=code_repository,
                branch_or_ref=app_config["branch"],
            )
        )

        # CodeBuild project that builds code analysis
        build_code_analysis = codebuild.Project(
            self, "Build-code-analysis",
            build_spec=codebuild.BuildSpec.from_object_to_yaml(build_code_analysis_spec),
            source=codebuild.Source.code_commit(
                repository=code_repository,
                branch_or_ref=app_config["branch"],
            )
        )

        # CodeBuild project that builds intergration
        build_intergration = codebuild.Project(
            self, "Build-intergration",
            build_spec=codebuild.BuildSpec.from_object_to_yaml(build_intergration_spec),
            source=codebuild.Source.code_commit(
                repository=code_repository,
                branch_or_ref=app_config["branch"],
            )
        )

        # CodeBuild project that builds load test
        build_load_test = codebuild.Project(
            self, "Build-load-test",
            build_spec=codebuild.BuildSpec.from_object_to_yaml(build_load_test_spec),
            source=codebuild.Source.code_commit(
                repository=code_repository,
                branch_or_ref=app_config["branch"],
            )
        )

        #import values                                                        
        task_definition_arn=Fn.import_value("task-definition-arn-dev")
        task_definition_task_role=Fn.import_value("task-definition-task-role-dev")
        task_definition_execution_role=Fn.import_value("task-definition-execution-role-dev")
        repository_name=Fn.import_value("repository-name-repository-account")
        repository_uri=Fn.import_value("repository-uri-repository-account")

        # CodeBuild project that builds the Docker image
        build_image = codebuild.Project(
            self, "BuildImage",
            build_spec=codebuild.BuildSpec.from_object_to_yaml(build_image_spec),
            source=codebuild.Source.code_commit(
                repository=code_repository,
                branch_or_ref=app_config["branch"],
            ),
            environment=codebuild.BuildEnvironment(
                privileged=True
            ),

            environment_variables={
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=env.account),
                "REGION": codebuild.BuildEnvironmentVariable(value=env.region),
                "IMAGE_TAG": codebuild.BuildEnvironmentVariable(value="latest"),
                "IMAGE_REPO_NAME": codebuild.BuildEnvironmentVariable(value=repository_name),
                "REPOSITORY_URI": codebuild.BuildEnvironmentVariable(value=repository_uri),
                "TASK_DEFINITION_ARN": codebuild.BuildEnvironmentVariable(value=task_definition_arn),
                "TASK_ROLE_ARN": codebuild.BuildEnvironmentVariable(value=task_definition_task_role),
                "EXECUTION_ROLE_ARN": codebuild.BuildEnvironmentVariable(value= task_definition_execution_role)
            }
        )
        ecr_repository=ecr.Repository.from_repository_name(self,"ecr_repo",repository_name)
        # Grants CodeBuild project access to pull/push images from/to ECR repo
        ecr_repository.grant_pull_push(build_image)

        # Lambda function that triggers CodeBuild image build project
        trigger_code_build = lambdaFunc.Function(
            self, "BuildLambda",
            architecture=lambdaFunc.Architecture.ARM_64,
            code=lambdaFunc.Code.from_asset("lambda"),
            handler="trigger-build.handler",
            runtime=lambdaFunc.Runtime.NODEJS_20_X,
            environment={
                "CODEBUILD_PROJECT_NAME": build_image.project_name,
                "REGION": env.region
            },
            # Allows this Lambda function to trigger the buildImage CodeBuild project
            initial_policy=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["codebuild:StartBuild"],
                    resources=[build_image.project_arn]
                )
            ]
        )

        # Triggers a Lambda function using AWS SDK
        trigger_lambda = custom.AwsCustomResource(
            self, "BuildLambdaTrigger",
            install_latest_aws_sdk=True,
            policy=custom.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunction"],
                    resources=[trigger_code_build.function_arn],
                )
            ]),
            on_create={
                "service": "Lambda",
                "action": "invoke",
                "physical_resource_id": custom.PhysicalResourceId.of("id"),
                "parameters": {
                    "FunctionName": trigger_code_build.function_name,
                    "InvocationType": "Event",
                },
            },
            on_update={
                "service": "Lambda",
                "action": "invoke",
                "parameters": {
                    "FunctionName": trigger_code_build.function_name,
                    "InvocationType": "Event",
                },
            }
        )

        # Creates the source stage for CodePipeline
        source_stage = codepipeline.StageProps(
            stage_name="Source",
            actions=[
                codepipeline_actions.CodeCommitSourceAction(
                    action_name="CodeCommit",
                    branch=app_config["branch"],
                    output=source_artifact,
                    repository=code_repository
                )
            ]
        )

        # Creates the build image stage for CodePipeline
        build_image_stage = codepipeline.StageProps(
            stage_name="Build-image",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="DockerBuildPush",
                    input=codepipeline.Artifact("SourceArtifact"),
                    project=build_image,
                    outputs=[build_image_artifact]
                )
            ]
        )

        # Creates the build stage for CodePipeline
        build_stage = codepipeline.StageProps(
            stage_name="Build-build",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="build",
                    input=codepipeline.Artifact("SourceArtifact"),
                    project=build_build,
                    outputs=[build_build_artifact]
                )
            ]
        )

        # Creates the unit test stage for CodePipeline
        build_unittest_stage = codepipeline.StageProps(
            stage_name="Build-unittest",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="unit-test",
                    input=codepipeline.Artifact("SourceArtifact"),
                    project=build_unittest,
                    outputs=[build_unittest_artifact]
                )
            ]
        )

        # Creates the code analysis stage for CodePipeline
        build_code_analysis_stage = codepipeline.StageProps(
            stage_name="Build-code-analysis",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="code-analysis",
                    input=codepipeline.Artifact("SourceArtifact"),
                    project=build_code_analysis,
                    outputs=[build_code_analysis_artifact]
                )
            ]
        )

        # Creates the intergration stage for CodePipeline
        build_intergration_stage = codepipeline.StageProps(
            stage_name="Build-intergratution",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="intergratution",
                    input=codepipeline.Artifact("SourceArtifact"),
                    project=build_intergration,
                    outputs=[build_intergration_artifact]
                )
            ]
        )

        # Creates the load test stage for CodePipeline
        build_load_test_stage = codepipeline.StageProps(
            stage_name="Build-load-test",
            actions=[
                codepipeline_actions.CodeBuildAction(
                    action_name="load-test",
                    input=codepipeline.Artifact("SourceArtifact"),
                    project=build_load_test,
                    outputs=[build_loadtest_artifact]
                )
            ]
        )
        
        #import dev values
        cluster_dev= Fn.import_value("ECS-cluster-dev")
        service_dev= Fn.import_value("ECS-Service-dev")
        listener_arn_dev=Fn.import_value("listener-dev")
        blue_target_group_arn_dev=Fn.import_value("tgblue-dev")
        green_target_group_arn_dev=Fn.import_value("tggreen-dev")
        alb_sg_id_dev=Fn.import_value("albsg-dev")


        # Creates a new CodeDeploy Deployment Group for Dev
        deployment_group_dev = codedeploy.EcsDeploymentGroup(
            self, "CodeDeployGroup-Dev",
            service=ecs.FargateService.from_fargate_service_attributes(self,"service-dev",service_arn=service_dev, cluster=ecs.Cluster.from_cluster_arn(self,"cluster-dev",cluster_arn=cluster_dev)),
            # Configurations for CodeDeploy Blue/Green deployments
            blue_green_deployment_config=codedeploy.EcsBlueGreenDeploymentConfig(
                listener=elb.ApplicationListener.from_application_listener_attributes(self,"listener-dev",listener_arn=listener_arn_dev,security_group=ec2.SecurityGroup.from_security_group_id(self,"sg-dev",alb_sg_id_dev)),
                blue_target_group=elb.ApplicationTargetGroup.from_target_group_attributes(self,"blue_tg-dev",target_group_arn=blue_target_group_arn_dev),
                green_target_group=elb.ApplicationTargetGroup.from_target_group_attributes(self,"green_tg-dev",target_group_arn=green_target_group_arn_dev)
            )
        )

        # Creates the deploy dev stage for CodePipeline
        deploy_dev_stage = codepipeline.StageProps(
            stage_name="Deploy-dev",
            actions=[
                codepipeline_actions.CodeDeployEcsDeployAction(
                    action_name="EcsDeploy",
                    app_spec_template_input=build_image_artifact,
                    task_definition_template_input=build_image_artifact,
                    deployment_group=deployment_group_dev
                )
            ]
        )


        #import staging values
        cluster_staging= Fn.import_value("ECS-cluster-staging")
        service_staging= Fn.import_value("ECS-Service-staging")
        listener_arn_staging=Fn.import_value("listener-staging")
        blue_target_group_arn_staging=Fn.import_value("tgblue-staging")
        green_target_group_arn_staging=Fn.import_value("tggreen-staging")
        alb_sg_id_staging=Fn.import_value("albsg-staging")


        # Creates a new CodeDeploy Deployment Group for staging
        deployment_group_staging = codedeploy.EcsDeploymentGroup(
            self, "CodeDeployGroup-Staging",
            service=ecs.FargateService.from_fargate_service_attributes(self,"service-stg",service_arn=service_staging, cluster=ecs.Cluster.from_cluster_arn(self,"cluster-stg",cluster_arn=cluster_staging)),
            # Configurations for CodeDeploy Blue/Green deployments
            blue_green_deployment_config=codedeploy.EcsBlueGreenDeploymentConfig(
                listener=elb.ApplicationListener.from_application_listener_attributes(self,"listener-stg",listener_arn=listener_arn_staging,security_group=ec2.SecurityGroup.from_security_group_id(self,"sg-stg",alb_sg_id_staging)),
                blue_target_group=elb.ApplicationTargetGroup.from_target_group_attributes(self,"blue_tg-stg",target_group_arn=blue_target_group_arn_staging),
                green_target_group=elb.ApplicationTargetGroup.from_target_group_attributes(self,"green_tg-stg",target_group_arn=green_target_group_arn_staging)
            )
        )

        # Creates the deploy staging stage for CodePipeline
        deploy_staging_stage = codepipeline.StageProps(
            stage_name="Deploy-staging",
            actions=[
                codepipeline_actions.CodeDeployEcsDeployAction(
                    action_name="EcsDeploy",
                    app_spec_template_input=build_image_artifact,
                    task_definition_template_input=build_image_artifact,
                    deployment_group=deployment_group_staging
                )
            ]
        )

        #import production values
        cluster_production= Fn.import_value("ECS-cluster-production")
        service_production= Fn.import_value("ECS-Service-production")
        listener_arn_production=Fn.import_value("listener-production")
        blue_target_group_arn_production=Fn.import_value("tgblue-production")
        green_target_group_arn_production=Fn.import_value("tggreen-production")
        alb_sg_id_production=Fn.import_value("albsg-production")


        # Creates a new CodeDeploy Deployment Group for production
        deployment_group_production = codedeploy.EcsDeploymentGroup(
            self, "CodeDeployGroup-production",
            service=ecs.FargateService.from_fargate_service_attributes(self,"service-prd",service_arn=service_production, cluster=ecs.Cluster.from_cluster_arn(self,"cluster-prd",cluster_arn=cluster_production)),
            # Configurations for CodeDeploy Blue/Green deployments
            blue_green_deployment_config=codedeploy.EcsBlueGreenDeploymentConfig(
                listener=elb.ApplicationListener.from_application_listener_attributes(self,"listener-prd",listener_arn=listener_arn_production,security_group=ec2.SecurityGroup.from_security_group_id(self,"sg-prd",alb_sg_id_production)),
                blue_target_group=elb.ApplicationTargetGroup.from_target_group_attributes(self,"blue_tg-prd",target_group_arn=blue_target_group_arn_production),
                green_target_group=elb.ApplicationTargetGroup.from_target_group_attributes(self,"green_tg-prd",target_group_arn=green_target_group_arn_production)
            )
        )

        # Creates the manual approval stage for CodePipeline
        manual_approval_action = codepipeline_actions.ManualApprovalAction(
            action_name="Approve",
        )
        manual_approval_stage = codepipeline.StageProps(
            stage_name="ApprovalProduction",
             actions=[
                manual_approval_action
            ]
        )
        adminRole = iam.Role.from_role_arn(self, "Admin", Arn.format(ArnComponents(service="iam", resource="role", resource_name="Admin"), self))

        
        # Creates the deploy production stage for CodePipeline
        deploy_production_stage = codepipeline.StageProps(
            stage_name="Deploy-production",
            actions=[

                codepipeline_actions.CodeDeployEcsDeployAction(
                    action_name="EcsDeploy",
                    app_spec_template_input=build_image_artifact,
                    task_definition_template_input=build_image_artifact,
                    deployment_group=deployment_group_production
                )
            ]
        )

        

        # Creates an AWS CodePipeline with source, build, and deploy stages
        pipeline = codepipeline.Pipeline(
            self, "workflowPipeline",
            pipeline_name="workflow-Pipeline",
            stages=[source_stage,build_stage, build_unittest_stage, build_code_analysis_stage, build_image_stage, deploy_dev_stage,build_intergration_stage, deploy_staging_stage,build_load_test_stage,manual_approval_stage, deploy_production_stage]
        )

        pipeline_topic = sns.Topic(self, "pipeline-topic")
        

        pipeline.notify_on_any_action_state_change(
        "pipeline-notify",
        target=pipeline_topic
        )

        with open("./lambda/notify_pipeline.py", encoding="utf8") as fp:
            handler_code = fp.read()

        notify_lambda=lambdaFunc.Function(
            self, "NotifyCodePiplne",
            architecture=lambdaFunc.Architecture.ARM_64,
            code=lambdaFunc.InlineCode(
                        handler_code),
            handler="index.lambda_handler",
            runtime=lambdaFunc.Runtime.PYTHON_3_10,
            environment={
                "WEBHOOK_URL_SLACK": webhook_url_slack,
                "REGION": env.region
            }
        )
        notify_lambda.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"))

        notify_lambda.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AmazonSNSReadOnlyAccess"))

        manual_approval_action.grant_manual_approval(adminRole)

        sns.Subscription(self, "NotifySubscription",
            topic=pipeline_topic,
            endpoint=notify_lambda.function_arn,
            protocol=sns.SubscriptionProtocol.LAMBDA
        )