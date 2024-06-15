from aws_cdk import (
    Environment,
    Stack,
    CfnOutput,
    aws_ecr as ecr,
)
from constructs import Construct
from typing import Dict, Mapping, Any
from utils.constants import Constants
from utils.functions_common import create_resource_name


class ecrStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        env: Environment,
        environment,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, env=env,**kwargs)

        # Create a ECR repository
        self.ecr_repository = ecr.Repository(self, "ecr-demo",
                                             )
        
        CfnOutput(self, "repository_nameOutput", value=self.ecr_repository.repository_name, export_name=f"repository-name-{environment}")
        CfnOutput(self, "repository_uriOutput", value=self.ecr_repository.repository_uri, export_name=f"repository-uri-{environment}")
