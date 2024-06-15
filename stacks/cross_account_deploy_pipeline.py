from __future__ import annotations

from aws_cdk import (
    DefaultStackSynthesizer,
    Environment,
    FeatureFlags,
    Stack,
    Stage,
    Tags,
    aws_codecommit as codecommit,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as codepipeline_actions,
    aws_iam as iam,
    pipelines,
)
from constructs import Construct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, cast

import cdk_nag
import dataclasses
import jsii

__all__ = ["CrossAccountDeployPipelines"]

REQUIRED_FEATURE_FLAGS = [
    "@aws-cdk/aws-codepipeline:crossAccountKeyAliasStackSafeResourceName",
    "@aws-cdk/aws-iam:minimizePolicies",
    "@aws-cdk/aws-iam:standardizedServicePrincipals",
    "@aws-cdk/aws-kms:defaultKeyPolicies",
    "@aws-cdk/aws-s3:grantWriteWithoutAcl",
    "@aws-cdk/core:enablePartitionLiterals",
    "@aws-cdk/core:enableStackNameDuplicates",
    "@aws-cdk/core:newStyleStackSynthesis",
    "aws-cdk:enableDiffNoFail",
]

DEFAULT_DEPLOY_CDK_QUALIFIER = "hnb659fds"
DEFAULT_PIPELINE_CDK_QUALIFIER = "hnb659fds"
DEFAULT_CDK_CLI_VERSION = "latest"
DEFAULT_PIP_INSTALL_ARGS = "-r requirements.txt"

PIPELINE_SOURCE_REPOSITORY_BRANCH_PREFIX = "deploy/"
CI_SUPPORT_TOOLS_REPOSITORY_NAME = "ci-support-scripts-repository"
CI_SUPPORT_TOOLS_REPOSITORY_BRANCH = "deploy/support"

CANARY_WAVE_NAME = "Canary"
DEPLOY_WAVE_NAME = "Deploy"
APPROVE_CDK_DIFF_ACTION_ID = "ApproveCdkDiff"
DESCRIBE_CHANGE_SET_ACTION_ID = "DescribeChangeSet"
APPROVE_CHANGE_SET_ACTION_ID = "ApproveChangeSet"


@dataclass
class PipelineCommonConfig:
    app_name: str
    project_name: Optional[str]
    cdk_qualifier: str
    cdk_cli_version_override: Optional[str]
    pip_install_args_override: Optional[str]
    repository_branch_prefix: str
    ci_support_tools_repository_branch: str
    pipeline_env: Environment
    pipeline_region_name: str
    pipeline_cdk_qualifier: str


@dataclass
class PipelineConfig:
    common: PipelineCommonConfig
    pipeline_name: str
    target_environment_name: str
    repository_name: str
    repository_branch: str
    canary_stages: Sequence[Stage]
    deploy_stages: Sequence[Stage]
    enable_pipeline_self_diff_check: bool


class CrossAccountDeployPipelines:

    def __init__(
        self,
        scope: Construct,
        *,
        app_name: str,
        project_name: Optional[str] = None,
        cdk_qualifier: str = DEFAULT_DEPLOY_CDK_QUALIFIER,
        cdk_cli_version_override: Optional[str] = None,
        pip_install_args_override: Optional[str] = None,
        repository_branch_prefix_override: Optional[str] = None,
        ci_support_tools_repository_branch_override: Optional[str] = None,
        pipeline_env: Environment,
        pipeline_region_name_override: Optional[str] = None,
        pipeline_cdk_qualifier: str = DEFAULT_PIPELINE_CDK_QUALIFIER,
        create_meta_pipelines: bool = True,
    ):
       
        assert pipeline_env.region is not None 

        self.stages: Dict[str, CrossAccountDeployPipelineStage] = {}
        self.meta_stages: Dict[str, CrossAccountDeployPipelineStage] = {}

        self.scope = scope
        self.create_meta_pipelines = create_meta_pipelines

        self.config = PipelineCommonConfig(
            app_name=app_name,
            project_name=project_name,
            cdk_qualifier=cdk_qualifier,
            cdk_cli_version_override=cdk_cli_version_override,
            pip_install_args_override=pip_install_args_override,
            repository_branch_prefix=repository_branch_prefix_override
            or PIPELINE_SOURCE_REPOSITORY_BRANCH_PREFIX,
            ci_support_tools_repository_branch=ci_support_tools_repository_branch_override
            or CI_SUPPORT_TOOLS_REPOSITORY_BRANCH,
            pipeline_env=pipeline_env,
            pipeline_region_name=pipeline_region_name_override or pipeline_env.region,
            pipeline_cdk_qualifier=pipeline_cdk_qualifier,
        )

    def add_target_environment(
        self,
        target_environment_name: str,
        *,
        canary_stages: Sequence[Stage] = [],
        deploy_stages: Sequence[Stage],
        pipeline_stage_name_override: Optional[str] = None,
        pipeline_stack_name_override: Optional[str] = None,
        pipeline_name_override: Optional[str] = None,
        repository_name_override: Optional[str] = None,
        repository_branch_suffix_override: Optional[str] = None,
        enable_pipeline_self_diff_check: bool = True,
    ) -> CrossAccountDeployPipelineStage:
        
        if target_environment_name in self.stages:
            raise ValueError("The specified target environment already exists")

        if len(canary_stages) == 0 and len(deploy_stages) == 0:
            raise ValueError("No stages are provided")

        if self.config.project_name is not None:
            app_qualified_name = f"{self.config.app_name}-{self.config.project_name}-{target_environment_name}-{self.config.pipeline_region_name}"
        else:
            app_qualified_name = f"{self.config.app_name}-{target_environment_name}-{self.config.pipeline_region_name}"

        pipeline_stage_name = (
            pipeline_stage_name_override
            or f"pipeline-{target_environment_name}-{self.config.pipeline_region_name}"
        )
        pipeline_stage_name = pipeline_stage_name.replace("/", "-")

        pipeline_stack_name = pipeline_stack_name_override or f"Pipeline-{app_qualified_name}"
        pipeline_stack_name = pipeline_stack_name.replace("/", "-")
        pipeline_name = pipeline_name_override or f"cdkpipeline-{app_qualified_name}"
        pipeline_name = pipeline_name.replace("/", "-")

        repository_name = repository_name_override or f"{self.config.app_name}"
        repository_branch_suffix = repository_branch_suffix_override or target_environment_name
        repository_branch = "deploy/dev"

        config = PipelineConfig(
            common=self.config,
            pipeline_name=pipeline_name,
            target_environment_name=target_environment_name,
            repository_name=repository_name,
            repository_branch=repository_branch,
            canary_stages=canary_stages,
            deploy_stages=deploy_stages,
            enable_pipeline_self_diff_check=enable_pipeline_self_diff_check,
        )

        pipeline_stage = CrossAccountDeployPipelineStage(
            self.scope,
            pipeline_stage_name,
            pipeline_stack_name=pipeline_stack_name,
            config=config,
        )

        self.stages[target_environment_name] = pipeline_stage

        if self.create_meta_pipelines:

            meta_config = PipelineConfig(
                common=dataclasses.replace(
                    self.config,
                    cdk_qualifier=self.config.pipeline_cdk_qualifier,
                ),
                pipeline_name=f"meta-{pipeline_name}",
                target_environment_name=target_environment_name,
                repository_name=repository_name,
                repository_branch=repository_branch,
                canary_stages=[],
                deploy_stages=[pipeline_stage],
                enable_pipeline_self_diff_check=enable_pipeline_self_diff_check,
            )

            meta_stage = CrossAccountDeployPipelineStage(
                self.scope,
                f"meta-{pipeline_stage_name}",
                pipeline_stack_name=f"Meta-{pipeline_stack_name}",
                config=meta_config,
            )

            self.meta_stages[target_environment_name] = meta_stage

        return pipeline_stage


class CrossAccountDeployPipelineStage(Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        pipeline_stack_name: str,
        config: PipelineConfig,
        **kwargs,
    ):
        super().__init__(scope, construct_id, env=config.common.pipeline_env, **kwargs)

        self.pipeline_stack = CrossAccountDeployPipelineStack(
            self,
            "Pipeline",
            stack_name=pipeline_stack_name,
            config=config,
            synthesizer=DefaultStackSynthesizer(qualifier=config.common.pipeline_cdk_qualifier),
        )


class CrossAccountDeployPipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: PipelineConfig,
        **kwargs,
    ):
        super().__init__(scope, construct_id, env=config.common.pipeline_env, **kwargs)

        # TODO: CodePipeline support 
        # TODO: Add notifications

        # Ensure consistent behaviors among different pipeline deployments:
        flags = FeatureFlags.of(self)
        for flag_name in REQUIRED_FEATURE_FLAGS:
            if not flags.is_enabled(flag_name):
                raise RuntimeError(f"CDK feature flag {flag_name} must be enabled")

        # Get this stack's parent Stage:
        parent_stage = Stage.of(self)
        assert parent_stage is not None

        # Drop stages with no stacks:
        canary_stages = PipelineUtils.filter_deployable_stages(config.canary_stages)
        deploy_stages = PipelineUtils.filter_deployable_stages(config.deploy_stages)

        # Pipeline input - CDK source code repository:
        pipeline_source_repository = codecommit.Repository.from_repository_name(
            self, "PipelineSourceRepository", config.repository_name
        )
        pipeline_source = pipelines.CodePipelineSource.code_commit(
            pipeline_source_repository, config.repository_branch
        )

        # Pipeline input - CI support tools repository:
        ci_support_tools_repository = codecommit.Repository.from_repository_name(
            self, "CiSupportToolsRepository", CI_SUPPORT_TOOLS_REPOSITORY_NAME
        )
        ci_support_tools_source = pipelines.CodePipelineSource.code_commit(
            ci_support_tools_repository,
            config.common.ci_support_tools_repository_branch,
            trigger=codepipeline_actions.CodeCommitTrigger.NONE,
        )

        # CodePipeline action role - CodeBuild:
        codepipeline_build_action_policy = self.__create_codepipeline_build_action_policy(
            pipeline_name=config.pipeline_name,
        )
        codepipeline_build_action_role = iam.Role.without_policy_updates(
            iam.Role(
                self,
                "CodePipelineBuildActionRole",
                assumed_by=iam.PrincipalWithConditions(
                    iam.AccountRootPrincipal(),
                    {"Bool": {"aws:ViaAWSService": "codepipeline.amazonaws.com"}},
                ),
                managed_policies=[codepipeline_build_action_policy],
            )
        )

        # CodePipeline action role - ApproveCdkDiff and ApproveChangeSet:
        approve_action_role = iam.Role.without_policy_updates(
            iam.Role(
                self,
                "ApproveActionRole",
                assumed_by=iam.PrincipalWithConditions(
                    iam.AccountRootPrincipal(),
                    {"Bool": {"aws:ViaAWSService": "codepipeline.amazonaws.com"}},
                ),
            )
        )

        # CodeBuild step common IAM policies:
        codebuild_step_default_policy = self.__create_codebuild_step_default_policy()
        assume_cdk_lookup_role_policy = self.__generate_assume_cdk_lookup_role_policy(
            canary_stages=canary_stages,
            deploy_stages=deploy_stages,
            cdk_qualifier=config.common.cdk_qualifier,
        )

        # CodeBuild step role - CDK synth:
        cdk_synth_step_role_inner = iam.Role(
            self,
            "CdkSynthStepRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            managed_policies=[codebuild_step_default_policy, assume_cdk_lookup_role_policy],
        )
        cdk_synth_step_role = iam.Role.without_policy_updates(cdk_synth_step_role_inner)

        # CodeBuild step role - Describe Change Set:
        describe_change_set_step_role_inner = iam.Role(
            self,
            "DescribeChangeSetStepRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            managed_policies=[codebuild_step_default_policy, assume_cdk_lookup_role_policy],
            inline_policies={
                "InlinePolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "codepipeline:GetPipeline",
                                "codepipeline:GetPipelineState",
                            ],
                            resources=[
                                f"arn:aws:codepipeline:{self.region}:{self.account}:{config.pipeline_name}",
                            ],
                        )
                    ]
                )
            },
        )
        describe_change_set_step_role = iam.Role.without_policy_updates(
            describe_change_set_step_role_inner
        )

        # Define CDK synth step:
        diff_targets = set(f"{stage.stage_name}/*" for stage in canary_stages + deploy_stages)
        synth_env = {"CDK_DIFF_TARGETS": " ".join(sorted(diff_targets))}
        fail_on_pipeline_self_diff_str = str(config.enable_pipeline_self_diff_check).lower()
        synth_step = pipelines.CodeBuildStep(
            "SynthStep",
            input=pipeline_source,
            install_commands=[
                f"npm install -g aws-cdk@{config.common.cdk_cli_version_override or DEFAULT_CDK_CLI_VERSION}",
                f"pip install {config.common.pip_install_args_override or DEFAULT_PIP_INSTALL_ARGS}",
            ],
            commands=[
                "cdk synth -q",
                f"cdk diff -a cdk.out/ {parent_stage.stage_name}/* --fail {fail_on_pipeline_self_diff_str} || {{ echo 'ERROR: Please update this pipeline first.'; false; }}",
                "cdk diff -a cdk.out/ ${CDK_DIFF_TARGETS}",
            ],
            env=synth_env,
            action_role=codepipeline_build_action_role,
            # NOTE: Ignoring known IRole implementation issue
            role=cdk_synth_step_role,  # type: ignore
        )

        # Create CodePipeline:
        pipeline = pipelines.CodePipeline(
            self,
            "Pipeline",
            pipeline_name=config.pipeline_name,
            synth=synth_step,
            # NOTE: Used by self-mutation and asset publishing steps:
            cli_version=config.common.cdk_cli_version_override,
            cross_account_keys=True,
            self_mutation=False,
        )
        pipeline_tags = Tags.of(pipeline)
        pipeline_tags.add("Repository", config.repository_name)
        pipeline_tags.add("Pipeline", config.pipeline_name)
        pipeline_tags.add("TargetEnvironment", config.target_environment_name)

        # Create Canary wave:
        canary_wave = pipeline.add_wave(CANARY_WAVE_NAME)
        for canary_stage in canary_stages:
            canary_wave.add_stage(canary_stage)

        # Create Deploy wave:
        deploy_wave = pipeline.add_wave(
            DEPLOY_WAVE_NAME,
            pre=[
                ManualApprovalStep(
                    APPROVE_CDK_DIFF_ACTION_ID,
                    comment="Check Build action logs and confirm the details.",
                    role=approve_action_role,
                )
            ],
        )

        # Inject Describe Change Set and Approve Change Set steps to each deploy stage:
        for deploy_stage in deploy_stages:
            stack_steps = self.__create_deploy_stage_stack_steps(
                deploy_stage,
                pipeline_name=config.pipeline_name,
                ci_support_tools_source=ci_support_tools_source,
                # NOTE: Ignoring known IRole implementation issue 
                describe_change_set_action_role=codepipeline_build_action_role,  # type: ignore
                describe_change_set_step_role=describe_change_set_step_role,  # type: ignore
                approve_change_set_action_role=approve_action_role,  # type: ignore
                cdk_qualifier=config.common.cdk_qualifier,
            )
            deploy_wave.add_stage(deploy_stage, stack_steps=stack_steps)

        # Build the pipeline internals to allow access to `pipeline.pipeline`:
        pipeline.build_pipeline()

        # Add additional permissions on artifact bucket and its encryption key:
        self.__add_codebuild_step_codepipeline_permissions(
            pipeline.pipeline,
            cdk_synth_step_role_inner,
            describe_change_set_step_role_inner,
        )

        # Add additional permissions to perform CDK diff on the pipeline stage's stacks themselves:
        cdk_synth_step_role_inner.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "cloudformation:DescribeStacks",
                    "cloudformation:GetTemplate",
                ],
                resources=[
                    f"arn:aws:cloudformation:*:{self.account}:stack/{stack.stack_name}/*"
                    for stack in PipelineUtils.get_stacks(parent_stage)
                ],
            )
        )

        cdk_nag.NagSuppressions.add_stack_suppressions(
            self,
            [
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-IAM5",
                    reason="This stack needs to use wildcard permissions to allow for role reuse within the stack.",
                ),
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-KMS5",
                    reason="This stack contains a KMS key used by CodePipeline, which does not need key rotation.",
                ),
                cdk_nag.NagPackSuppression(
                    id="AwsSolutions-S1",
                    reason="This stack contains a S3 Bucket used by CodePipeline, which does not need access logging.",
                ),
            ],
        )

    def __create_codepipeline_build_action_policy(
        self,
        *,
        pipeline_name: str,
    ) -> iam.ManagedPolicy:
        return iam.ManagedPolicy(
            self,
            "CodePipelineBuildActionPolicy",
            document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=[
                            "codebuild:BatchGetBuilds",
                            "codebuild:StartBuild",
                            "codebuild:StopBuild",
                        ],
                        resources=[f"arn:aws:codebuild:{self.region}:{self.account}:project/*"],
                        conditions={
                            "StringEquals": {"aws:ResourceTag/Pipeline": pipeline_name}
                        },
                    ),
                ]
            ),
        )

    def __create_codebuild_step_default_policy(self) -> iam.IManagedPolicy:
        return iam.ManagedPolicy(
            self,
            "CodeBuildStepDefaultPolicy",
            document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=[
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                        ],
                        resources=[
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/codebuild/*"
                        ],
                    ),
                    iam.PolicyStatement(
                        actions=[
                            "codebuild:BatchPutCodeCoverages",
                            "codebuild:BatchPutTestCases",
                            "codebuild:CreateReport",
                            "codebuild:CreateReportGroup",
                            "codebuild:UpdateReport",
                        ],
                        resources=[
                            f"arn:aws:codebuild:{self.region}:{self.account}:report-group/*",
                        ],
                    ),
                ]
            ),
        )

    def __generate_assume_cdk_lookup_role_policy(
        self,
        canary_stages: Sequence[Stage],
        deploy_stages: Sequence[Stage],
        cdk_qualifier: str,
    ) -> iam.IManagedPolicy:
        return iam.ManagedPolicy(
            self,
            "AssumeCdkLookupRolePolicy",
            document=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["sts:AssumeRole"],
                        resources=[
                            f"arn:aws:iam::*:role/cdk-{cdk_qualifier}-lookup-role-*",
                        ],
                        conditions={
                            "StringEquals": {
                                "iam:ResourceTag/aws-cdk:bootstrap-role": "lookup",
                                "aws:ResourceAccount": PipelineUtils.get_account_ids(
                                    [*canary_stages, *deploy_stages]
                                ),
                            }
                        },
                    )
                ]
            ),
        )

    def __add_codebuild_step_codepipeline_permissions(
        self,
        pipeline: codepipeline.Pipeline,
        *roles: iam.Role,
    ):
        assert pipeline.artifact_bucket.encryption_key is not None 
        for role in roles:
            pipeline.artifact_bucket.grant_read_write(role)
            pipeline.artifact_bucket.encryption_key.grant_encrypt_decrypt(role)
            pipeline.artifact_bucket.encryption_key.grant(role, "kms:DescribeKey")

    def __create_deploy_stage_stack_steps(
        self,
        deploy_stage: Stage,
        *,
        pipeline_name: str,
        ci_support_tools_source: pipelines.IFileSetProducer,
        describe_change_set_action_role: iam.IRole,  # For CodePipeline -> CodeBuild execution
        describe_change_set_step_role: iam.IRole,  # For CodeBuild project's own execution
        approve_change_set_action_role: iam.IRole,
        cdk_qualifier: str,
    ) -> Sequence[pipelines.StackSteps]:

        stacks = [
            cast(Stack, construct)
            for construct in deploy_stage.node.children
            if Stack.is_stack(construct)
        ]
        stack_steps = []

        for stack in stacks:

            describe_change_set_env = {
                "PIPELINE_NAME": pipeline_name,
                "PIPELINE_EXECUTION_ID": "#{codepipeline.PipelineExecutionId}",
                "CDK_QUALIFIER": cdk_qualifier,
            }

            describe_change_set_step = pipelines.CodeBuildStep(
                DESCRIBE_CHANGE_SET_ACTION_ID,
                additional_inputs={"tools": ci_support_tools_source},
                install_commands=["cd tools", "pip install -r requirements.txt"],
                commands=["python ./describe_change_set.py"],
                env=describe_change_set_env,
                action_role=describe_change_set_action_role,
                role=describe_change_set_step_role,
            )

            approve_change_set_step = ManualApprovalStep(
                APPROVE_CHANGE_SET_ACTION_ID,
                comment="Check Change Set details.",
                role=approve_change_set_action_role,
            )

            # Inject pipeline name tag to the stack for back-reference:
            stack.tags.set_tag("Pipeline", pipeline_name)

            stack_step = pipelines.StackSteps(
                stack=stack,
                change_set=pipelines.Step.sequence(
                    [
                        describe_change_set_step,
                        approve_change_set_step,
                    ]
                ),
            )
            stack_steps.append(stack_step)

        return stack_steps


@jsii.implements(pipelines.ICodePipelineActionFactory)
class ManualApprovalStep(pipelines.Step):
    """
    Manual approval step that optionally accepts a custom role.
    """

    def __init__(
        self,
        id: str,
        comment: Optional[str] = None,
        role: Optional[iam.IRole] = None,
    ):
        super().__init__(id)
        self.comment = comment
        self.role = role

    @jsii.member(jsii_name="produceAction")
    def produce_action(
        self,
        stage: codepipeline.IStage,
        *,
        action_name: str,
        run_order: jsii.Number,
        **kwargs,
    ) -> pipelines.CodePipelineActionFactoryResult:
        stage.add_action(
            codepipeline_actions.ManualApprovalAction(
                action_name=action_name,
                run_order=run_order,
                additional_information=self.comment,
                role=self.role,
            )
        )
        return pipelines.CodePipelineActionFactoryResult(run_orders_consumed=1)


class PipelineUtils:
    @staticmethod
    def filter_deployable_stages(stages: Sequence[Stage]) -> List[Stage]:
        """Filters out stages without stacks from the given list of stages."""
        return [stage for stage in stages if PipelineUtils.contains_stack(stage)]

    @staticmethod
    def contains_stack(stage: Stage) -> bool:
        """Checks whether a given stage contains one or more stack."""
        return len(PipelineUtils.get_stacks(stage)) > 0

    @staticmethod
    def get_stacks(stage: Stage) -> Sequence[Stack]:
        """Gets all stacks composed directly within the specified stage."""
        return [
            cast(Stack, construct)
            for construct in stage.node.children
            if Stack.is_stack(construct)
        ]

    @staticmethod
    def get_account_ids(stages: Sequence[Stage]) -> Sequence[str]:
        """Gets all unique account IDs among all stacks within the specified list of stages."""
        stage_accounts = [stage.account for stage in stages if stage.account is not None]
        stack_accounts = [
            stack.account
            for stage in stages
            for stack in PipelineUtils.get_stacks(stage)
            if stack.account is not None
        ]
        return sorted(set(stage_accounts + stack_accounts))
