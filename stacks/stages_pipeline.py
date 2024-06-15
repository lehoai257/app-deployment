from aws_cdk import Environment, Stage
from constructs import Construct
from typing import Any, Mapping, Dict

from stacks.workflow_pipeline_stack import workflowPipelineStack


class DeployStagePipeline(Stage):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment: str,
        env: Environment,
        region: str,
        app_config: Dict,
        webhook_url_slack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, env=env, **kwargs)

        stack_name_prefix = f"{environment}-{region}"
        resource_name_prefixs = {
            "environment": environment,
            "region": region
        }
        
        workflow_pipeline_stack = workflowPipelineStack(
            self,
            "WORKFLOW-PIPELINE",
            stack_name="WORKFLOW-PIPELINE",
            app_config=app_config,
            env=env,
            webhook_url_slack=webhook_url_slack
        ) 
       
