from utils.utils import print_colors, generate_name
from humans.human import Human
from humans.human_configs import HumanConfigs
from humans.human_appearance import HumanAppearance
from trajectory.trajectory import SystemConfig, Trajectory
import numpy as np
import socket, time, threading

class PrerecordedHuman(Human):
    def __init__(self, record_data, generate_appearance=True, name=None):
        if name is None:
            self.name = generate_name(20)
        else:
            self.name = name
        self.record_data = record_data
        self.t = 0
        self.current_step = 0
        self.max_steps = len(self.record_data)
        self.next_state = self.record_data[1]
        start = HumanConfigs.generate_config_from_pos_3(record_data[0][:3], speed=0)
        goal = HumanConfigs.generate_config_from_pos_3(record_data[-1][:3], speed=0)
        init_configs = HumanConfigs(start, goal)
        if(generate_appearance):
            appearance = HumanAppearance.generate_random_human_appearance(HumanAppearance)
        else:
            appearance = None
        super().__init__(name, appearance, init_configs)

        # print(self.record_data)
        # print("prerecorded agent start:", self.start_config.to_3D_numpy(), "goal:", self.goal_config.to_3D_numpy())
    
    def simulation_init(self, sim_params, sim_map, with_planner=True):
        """ Initializes important fields for the CentralSimulator"""
        self.params = sim_params
        self.obstacle_map = sim_map
        # Initialize system dynamics and planner fields
        self.system_dynamics = self._init_system_dynamics()
        self.vehicle_trajectory = Trajectory(dt=self.params.dt, n=1, k=0)

    def execute(self, state):
        self.current_step += 1 # Has executed one more step
        self.set_current_config(HumanConfigs.generate_config_from_pos_3(state[:3], speed=state[3]))
        # print(self.get_current_config().to_3D_numpy())
        null_command = np.array([[[0,0]]], dtype=np.float32) # dummy "command" since these agents "teleport"
        # NOTE: the format for the acceleration commands to the open loop for the robot is:
        # np.array([[[L, A]]], dtype=np.float32) where L is linear, A is angular
        t_seg, actions_nk2 = self.apply_control_open_loop(self.current_config,   
                                                        null_command, 1, sim_mode='ideal'
                                                        )
        self.vehicle_trajectory.append_along_time_axis(t_seg)

    def update(self, time):
        self.t = time
        if(self.current_step < self.max_steps):
            # continue jumping through states until time limit is reached
            while(self.t > self.next_state[-1]):
                self.execute(self.next_state)
                try:
                    self.next_state = self.record_data[self.current_step + 1]
                except IndexError:
                    self.next_state = self.record_data[-1] # last one
                    self.current_step = self.max_steps
                    break
        else:
            # tell the simulator this agent is done
            self.end_episode = True
            self.end_acting = True