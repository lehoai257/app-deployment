from aws_cdk import (
    Environment,
    Stack,
    CfnOutput,
    Fn,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_elasticloadbalancingv2 as elb,
    aws_codedeploy as codedeploy,
)
from constructs import Construct
from typing import Dict, Mapping, Any
from utils.constants import Constants
from utils.functions_common import create_resource_name

default_http_port = Constants.DEFAULT_HTTP_PORT
default_https_port = Constants.DEFAULT_HTTPS_PORT


class ecsClusterStack(Stack):

    # Define sercurity group for Load balancer
    def create_ecs_alb_sg(self, vpc):
        sg = ec2.SecurityGroup(
            self,
            id="ECS-ALB-SG",
            vpc=vpc,
            allow_all_outbound=False,
            description="ECS ALB Security Group"
        )
        sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(Constants.DEFAULT_CIDR_IPV4_ALL),
            connection=ec2.Port.all_tcp(),
            description="All",
        )
        sg.add_egress_rule(
            peer=ec2.Peer.ipv4(Constants.DEFAULT_CIDR_IPV4_ALL),
            connection=ec2.Port.all_tcp(),
            description="All",
        )

        return sg

    # Define sercurity group for Autoscaling
    def create_ecs_asg_sg(self, vpc, cidr, ports_app):
        sg = ec2.SecurityGroup(
            self,
            id="ECS-ASG-SG",
            vpc=vpc,
            allow_all_outbound=False,
            description="ECS ASG Security Group"
        )

        sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(cidr),
            connection=ec2.Port.tcp(ports_app["portHttp"]),
            description=f"ALB access {ports_app['portHttp']} port of EC2 in Autoscaling Group",
        )

        sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(Constants.DEFAULT_CIDR_IPV4_ALL),
            connection=ec2.Port.all_tcp(),
            description="All",
        )

        sg.add_egress_rule(
            peer=ec2.Peer.ipv4(Constants.DEFAULT_CIDR_IPV4_ALL),
            connection=ec2.Port.tcp(default_http_port),
            description="HTTP egress",
        )
        sg.add_egress_rule(
            peer=ec2.Peer.ipv4(Constants.DEFAULT_CIDR_IPV4_ALL),
            connection=ec2.Port.tcp(default_https_port),
            description="HTTPS egress",
        )
        sg.add_egress_rule(
            peer=ec2.Peer.ipv4(Constants.DEFAULT_CIDR_IPV4_ALL),
            connection=ec2.Port.all_tcp(),
            description="All",
        )
        return sg

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        resource_name_prefixs,
        cidr: str,
        ports_app: Dict,
        *,
        env: Environment,
        app_config: Dict,
        ecr_repository,
        environment,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, env=env, **kwargs)

        # Create VPC with public subnets and a s3 Enpoint gateway
        vpc = ec2.Vpc(self, "VPC",
                            max_azs=2,
                            cidr=cidr,
                            subnet_configuration=[
                                ec2.SubnetConfiguration(
                                    name="publicSubnet",
                                    subnet_type=ec2.SubnetType.PUBLIC,
                                    cidr_mask=24),
                            ],
                      gateway_endpoints={
                                "s3": ec2.GatewayVpcEndpointOptions(
                                    service=ec2.GatewayVpcEndpointAwsService.S3
                                )
                            }
                      )

        ecs_asg_sg = self.create_ecs_asg_sg(vpc, cidr, ports_app)
        ecs_alb_sg = self.create_ecs_alb_sg(vpc)

        alb_name = create_resource_name("ALB",
                                        resource_name_prefixs["environment"],
                                        resource_name_prefixs["region"])

        # Create ALB
        self.alb = elb.ApplicationLoadBalancer(self, "ecs_alb",
                                               vpc=vpc,
                                               vpc_subnets=ec2.SubnetSelection(
                                                   subnet_type=ec2.SubnetType.PUBLIC),
                                               internet_facing=True,
                                               security_group=ecs_alb_sg,
                                               load_balancer_name=alb_name,
                                               )

        # Creates a new blue Target Group that routes traffic from the public Application Load Balancer (ALB) to the
        http_target_group_blue = elb.ApplicationTargetGroup(
            self, "BlueTargetGroup",
            target_group_name=f"alb-blue-tg-{environment}",
            target_type=elb.TargetType.IP,
            port=app_config["portHttp"],
            vpc=vpc
        )

        # Creates a new green Target Group
        http_target_group_green = elb.ApplicationTargetGroup(
            self, "GreenTargetGroup",
            target_group_name=f"alb-green-tg-{environment}",
            target_type=elb.TargetType.IP,
            port=app_config["portHttp"],
            vpc=vpc
        )

        http_target_group_blue.configure_health_check(
            healthy_http_codes="200,301,302",
            healthy_threshold_count=3,
            unhealthy_threshold_count=5,
            path=f"/{app_config['appName']}/index.jsp"
        )

        http_target_group_green.configure_health_check(
            healthy_http_codes="200,301,302",
            healthy_threshold_count=3,
            unhealthy_threshold_count=5,
            path=f"/{app_config['appName']}/index.jsp"
        )

        # ALB listeners
        http_listener = self.alb.add_listener("http_listener",
                                              port=Constants.DEFAULT_HTTP_PORT,
                                              open=True,
                                              default_target_groups=[
                                                  http_target_group_blue],
                                                
                                              )

        # Create Task Definition
        task_definition = ecs.FargateTaskDefinition(
            self, "TaskDef",)
        repository_name=Fn.import_value("repository-name-repository-account")
        container = task_definition.add_container(
            "web",
            container_name="web",
            image=ecs.ContainerImage.from_ecr_repository(ecr.Repository.from_repository_name(self,"repo",repository_name)),
            memory_limit_mib=256
        )

        port_mapping = ecs.PortMapping(
            container_port=8080,
            host_port=8080,
            protocol=ecs.Protocol.TCP
        )

        container.add_port_mappings(port_mapping)

        # Create a cluster
        cluster = ecs.Cluster(
            self, 'EcsCluster',
            vpc=vpc,
            enable_fargate_capacity_providers=True,
        )

        # Create Service
        service = ecs.FargateService(
            self, "Service",
            service_name=f"ECS-Service-{environment}",
            desired_count=1,
            cluster=cluster,
            task_definition=task_definition,
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.CODE_DEPLOY
            ),
            assign_public_ip=True,
            enable_execute_command=True
        )

        # Adds the ECS service to the ALB target group
        service.attach_to_application_target_group(http_target_group_blue)

        execution_role_arn = task_definition.execution_role.role_arn if task_definition.execution_role else ""

        CfnOutput(self, "task_definition_execution_roleOutput", value=execution_role_arn, export_name=f"task-definition-execution-role-{environment}")

        CfnOutput(self, "Output",
                  value=f"""http://{self.alb.load_balancer_dns_name}""")
        CfnOutput(self, "clusterOutput", value=cluster.cluster_arn, export_name=f"ECS-cluster-{environment}")
        CfnOutput(self, "serviceOutput", value=service.service_arn, export_name=f"ECS-Service-{environment}")
        CfnOutput(self, "task_definition_arnOutput", value=task_definition.task_definition_arn, export_name=f"task-definition-arn-{environment}")
        CfnOutput(self, "task_definition_task_roleOutput", value=task_definition.task_role.role_arn, export_name=f"task-definition-task-role-{environment}")
        CfnOutput(self, "listenerOutput", value=http_listener.listener_arn, export_name=f"listener-{environment}")
        CfnOutput(self, "tgblueOutput", value=http_target_group_blue.target_group_arn, export_name=f"tgblue-{environment}")
        CfnOutput(self, "tggreenOutput", value=http_target_group_green.target_group_arn, export_name=f"tggreen-{environment}")
        CfnOutput(self, "albsbOutput", value=ecs_alb_sg.security_group_id, export_name=f"albsg-{environment}")
