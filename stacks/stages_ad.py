from aws_cdk import Environment, Stage
from constructs import Construct
from typing import Any, Mapping, Dict

from stacks.ecr_stack import ecrStack
# from stacks.workflow_pipeline_stack import workflowPipelineStack


class DeployStageAD(Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment: str,
        env: Environment,
        region: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, env=env, **kwargs)

        stack_name_prefix = f"{environment}-{region}"
        resource_name_prefixs = {
            "environment": environment,
            "region": region
        }
        

        self.ecr_stack=ecrStack(
            self,
            "ECR",
            stack_name=f"{stack_name_prefix}-ECR",
            env=env,
            environment=environment
        )

