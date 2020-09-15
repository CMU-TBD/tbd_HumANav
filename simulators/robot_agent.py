from utils.utils import *
from simulators.agent import Agent
from humans.human_configs import HumanConfigs
from trajectory.trajectory import SystemConfig
from params.central_params import create_robot_params
import numpy as np
import socket
import ast
import time
import threading
import sys


lock = threading.Lock()  # for asynchronous data sending


class RoboAgent(Agent):
    joystick_receiver_socket = None
    joystick_sender_socket = None
    host = None
    port_send = None
    port_recv = None

    def __init__(self, name, start_configs, trajectory=None):
        self.name = name
        super().__init__(start_configs.get_start_config(),
                         start_configs.get_goal_config(),
                         name=name, with_init=False)
        self.commands = []
        # robot's knowledge of the current state of the world
        self.world_state = None
        # josystick is ready once it has been sent an environment
        self.joystick_ready = False
        # To send the world state on the next joystick ping
        self.joystick_requests_world = False
        # whether or not to repeat the last joystick input
        self.repeat_joystick = False
        # told the joystick that the robot is powered off
        self.notified_joystick = False
        # used to keep the listener thread alive even if the robot isnt
        self.simulator_running = False

    def simulation_init(self, sim_map, with_planner=False):
        super().simulation_init(sim_map, with_planner=with_planner)
        self.params.robot_params = create_robot_params()
        self.repeat_freq = self.params.repeat_freq
        # simulation update init
        self.running = True
        self.last_command = None
        self.num_executed = 0  # keeps track of the latest command that is to be executed
        self.amnd_per_batch = 1

    # Getters for the robot class

    def get_name(self):
        return self.name

    def get_radius(self):
        return self.params.robot_params.physical_params.radius

    # Setters for the robot class
    def update_world(self, state):
        self.world_state = state

    def get_num_executed(self):
        return int(np.floor(len(self.commands) / self.amnd_per_batch))

    @staticmethod
    def generate_robot(configs, name=None, verbose=False):
        """
        Sample a new random robot agent from all required features
        """
        robot_name = "robot_agent"  # constant name for the robot since there will only ever be one
        # In order to print more readable arrays
        np.set_printoptions(precision=2)
        pos_2 = configs.get_start_config().to_3D_numpy()
        goal_2 = configs.get_goal_config().to_3D_numpy()
        if(verbose):
            print("Robot", robot_name, "at", pos_2, "with goal", goal_2)
        return RoboAgent(robot_name, configs)

    @staticmethod
    def generate_random_robot_from_environment(environment):
        """
        Sample a new robot without knowing any configs or appearance fields
        NOTE: needs environment to produce valid configs
        """
        configs = HumanConfigs.generate_random_human_config(environment)
        return RoboAgent.generate_robot(configs)

    def check_termination_conditions(self):
        """use this to take in a world state and compute obstacles (gen_agents/walls) to affect the robot"""
        # check for collisions with other gen_agents
        self.check_collisions(self.world_state)

        # enforce planning termination upon condition
        self._enforce_episode_termination_conditions()

        if(self.vehicle_trajectory.k >= self.collision_point_k):
            self.end_acting = True

        if(self.get_collided()):
            assert(self.termination_cause == 'Collision')
            self.power_off()

        if(self.get_completed()):
            assert(self.termination_cause == "Success")
            self.power_off()

    def execute(self):
        for _ in range(self.amnd_per_batch):
            if(not self.running):
                break
            self.check_termination_conditions()
            current_config = self.get_current_config()
            cmd_grp = self.commands[self.num_executed]
            num_cmds_in_grp = len(cmd_grp)
            # the command is indexed by self.num_executed and is safe due to the size constraints in the update()
            command = np.array([[cmd_grp]], dtype=np.float32)
            # NOTE: the format for the acceleration commands to the open loop for the robot is:
            # np.array([[[L, A]]], dtype=np.float32) where L is linear, A is angular
            t_seg, actions_nk2 = Agent.apply_control_open_loop(self, current_config,
                                                               command, num_cmds_in_grp,
                                                               sim_mode='ideal'
                                                               )
            self.num_executed += 1
            self.vehicle_trajectory.append_along_time_axis(
                t_seg, track_trajectory_acceleration=True)
            # act trajectory segment
            self.current_config = \
                SystemConfig.init_config_from_trajectory_time_index(
                    t_seg,
                    t=-1
                )
            if (self.params.verbose):
                print(self.get_current_config().to_3D_numpy())

    def update(self, iteration):
        if self.running:
            # only execute the most recent commands
            self.check_termination_conditions()
            if self.num_executed < len(self.commands):
                self.execute()
            # block joystick until recieves next command or finish sending world
            while (self.running and (self.joystick_requests_world or iteration >= self.get_num_executed())):
                time.sleep(0.001)
        else:
            self.power_off()

    def power_off(self):
        # if the robot is already "off" do nothing
        if(self.running):
            print("\nRobot powering off, received",
                  len(self.commands), "commands")
            self.running = False
            try:
                quit_message = self.world_state.to_json(
                    robot_on=False,
                    termination_cause=self.termination_cause
                )
                self.send_to_joystick(quit_message)
            except:
                return

    """BEGIN socket utils"""

    def send_sim_state(self):
        # send the (JSON serialized) world state per joystick's request
        if self.joystick_requests_world:
            world_state = self.world_state.to_json(
                robot_on=self.running,
                include_map=False
            )
            self.send_to_joystick(world_state)
            # immediately note that the world has been sent:
            self.joystick_requests_world = False

    def send_to_joystick(self, message: str):
        with lock:
            assert(isinstance(message, str))
            # Create a TCP/IP socket
            RoboAgent.joystick_sender_socket = \
                socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Connect the socket to the port where the server is listening
            server_address = ((RoboAgent.host, RoboAgent.port_send))
            try:
                RoboAgent.joystick_sender_socket.connect(server_address)
            except ConnectionRefusedError:  # used to turn off the joystick
                self.joystick_running = False
                # print("%sConnection closed by joystick%s" % (color_red, color_reset))
                return
            # Send data
            RoboAgent.joystick_sender_socket.sendall(bytes(message, "utf-8"))
            RoboAgent.joystick_sender_socket.close()

    def listen_to_joystick(self):
        """Constantly connects to the robot listener socket and receives information from the
        joystick about the input commands as well as the world requests
        """
        RoboAgent.joystick_receiver_socket.listen(1)
        while(self.simulator_running):
            connection, client = RoboAgent.joystick_receiver_socket.accept()
            data_b, response_len = conn_recv(connection, buffr_amnt=128)
            # close connection to be reaccepted when the joystick sends data
            connection.close()
            if(data_b is not b'' and response_len > 0):
                data_str = data_b.decode("utf-8")  # bytes to str
                if(not self.running):
                    # with the robot_on=False flag
                    self.send_sim_state()
                else:
                    self.manage_data(data_str)

    def is_keyword(self, data_str):
        # non json important keyword
        if(data_str == "sense"):
            self.joystick_requests_world = True
            self.send_sim_state()
            return True
        elif(data_str == "ready"):
            self.joystick_ready = True
            return True
        return False

    def manage_data(self, data_str: str):
        if(not self.is_keyword(data_str)):
            data = json.loads(data_str)
            # TODO: clean up this messy data management
            v_cmds: list = data["v_cmds"]
            w_cmds: list = data["w_cmds"]
            assert(len(v_cmds) == len(w_cmds))
            self.amnd_per_batch = len(v_cmds)
            for i in range(self.amnd_per_batch):
                np_data = np.array(
                    [v_cmds[i], w_cmds[i]], dtype=np.float32)
                # add at least one command
                self.commands.append(np_data)
                if(self.repeat_joystick):  # if need be, repeat n-1 times
                    repeat_amnt = int(np.floor(
                        (self.params.robot_params.physical_params.repeat_freq / self.amnd_per_batch) - 1))
                    for i in range(repeat_amnt):
                        # adds command to local list of individual commands
                        self.commands.append(np_data)

    @ staticmethod
    def establish_joystick_receiver_connection():
        """This is akin to a server connection (robot is server)"""
        RoboAgent.joystick_receiver_socket = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM)
        RoboAgent.joystick_receiver_socket.bind(
            (RoboAgent.host, RoboAgent.port_recv))
        # wait for a connection
        RoboAgent.joystick_receiver_socket.listen(1)
        print("Waiting for Joystick connection...")
        connection, client = RoboAgent.joystick_receiver_socket.accept()
        print("%sRobot---->Joystick connection established%s" %
              (color_green, color_reset))
        return connection, client

    @ staticmethod
    def establish_joystick_sender_connection():
        """This is akin to a client connection (joystick is client)"""
        RoboAgent.joystick_sender_socket = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM)
        address = ((RoboAgent.host, RoboAgent.port_send))
        try:
            RoboAgent.joystick_sender_socket.connect(address)
        except:
            print("%sUnable to connect to joystick%s" %
                  (color_red, color_reset))
            print("Make sure you have a joystick instance running")
            exit(1)
        assert(RoboAgent.joystick_sender_socket is not None)
        print("%sJoystick->Robot connection established%s" %
              (color_green, color_reset))

    @ staticmethod
    def close_robot_sockets():
        RoboAgent.joystick_sender_socket.close()
        RoboAgent.joystick_receiver_socket.close()

    """ END socket utils """
