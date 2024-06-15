from aws_cdk import Environment, Stage
from constructs import Construct
from typing import Any, Mapping, Dict

from stacks.ecs_stack import ecsClusterStack
from stacks.ecr_stack import ecrStack
# from stacks.workflow_pipeline_stack import workflowPipelineStack


class DeployStage(Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment: str,
        app_config: Dict,
        env: Environment,
        cidr: str,
        region: str,
        ecr_repository,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, env=env, **kwargs)

        stack_name_prefix = f"{environment}-{region}"
        resource_name_prefixs = {
            "environment": environment,
            "region": region
        }
        
        ecs_stack = ecsClusterStack(
            self,
            "ECS",
            resource_name_prefixs=resource_name_prefixs,
            stack_name=f"{stack_name_prefix}-ECS",
            env=env,
            cidr=cidr,
            ports_app=app_config,
            app_config=app_config,
            ecr_repository=ecr_repository,
            environment=environment
        )
