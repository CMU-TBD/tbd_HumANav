from utils.utils import *
from humans.human import Human
from humans.human_configs import HumanConfigs
from humans.human_appearance import HumanAppearance
from trajectory.trajectory import SystemConfig, Trajectory
from params.central_params import create_agent_params
from simulators.agent import Agent
import numpy as np
import socket
import time
import threading


class PrerecordedHuman(Human):
    def __init__(self, t_data, posn_data, generate_appearance=True, name=None):
        self.name = generate_name(20) if not name else name
        assert(len(t_data) == len(posn_data))
        self.t_data = t_data
        self.posn_data = posn_data
        self.sim_t = 0
        self.current_step = 0
        self.next_step = self.posn_data[1]
        self.world_state = None
        init_configs = HumanConfigs(posn_data[0], posn_data[-1])
        if(generate_appearance):
            appearance = HumanAppearance.generate_random_human_appearance(
                HumanAppearance)
        else:
            appearance = None
        super().__init__(name, appearance, init_configs)

    def get_start_time(self):
        return self.t_data[0]

    def get_end_time(self):
        return self.t_data[-1]

    def get_current_config(self, deepcpy=False):
        return super().get_config(self.posn_data[self.current_step], deepcpy=deepcpy)

    def get_current_time(self):
        return self.t_data[self.current_step]

    def get_completed(self):
        return self.end_acting and self.end_episode

    def simulation_init(self, sim_map, with_planner=True):
        """ Initializes important fields for the CentralSimulator"""
        self.params = create_agent_params(with_planner=with_planner)
        self.obstacle_map = sim_map
        # Initialize system dynamics and planner fields
        self.system_dynamics = Agent._init_system_dynamics(self)
        self.vehicle_trajectory = Trajectory(dt=self.params.dt, n=1, k=0)

    def execute(self, state, check_collisions_with_agents=False):
        if(check_collisions_with_agents):
            self.check_collisions(self.world_state, include_prerecs=False)
        self.current_step += 1  # Has executed one more step
        self.current_config = self.posn_data[self.current_step]
        # dummy "command" since these agents "teleport" from one step to another
        # below code is just to keep track of the agent's trajectories as they move
        null_command = np.array([[[0, 0]]], dtype=np.float32)
        t_seg, _ = Agent.apply_control_open_loop(self, self.current_config,
                                                 null_command, 1, sim_mode='ideal'
                                                 )
        self.vehicle_trajectory.append_along_time_axis(t_seg)

    def update(self, sim_t, world_state):
        self.sim_t = sim_t
        self.world_state = world_state
        self.has_collided = False
        if(self.current_step < len(self.t_data)):
            # continue jumping through states until time limit is reached
            while(not self.has_collided and self.sim_t > self.get_current_time()):
                self.execute(self.next_step)
                try:
                    self.next_step = self.posn_data[self.current_step]
                except IndexError:
                    self.next_step = self.posn_data[-1]  # last one
                    self.current_step = len(self.t_data) - 1
                    break
        else:
            # tell the simulator this agent is done
            self.end_episode = True
            self.end_acting = True

    def end(self):
        """Instantly teleport the agents to the last position in their trejectory
        """
        self.set_current_config(self.goal_config)

    """ BEGIN GENERATION UTILS """

    @staticmethod
    def gather_times(ped_i, time_delay: float, start_frame: int, start_t: float, fps: float):
        times = []
        for i, f in enumerate(ped_i['frame']):
            relative_time = (f - start_frame) * (1. / fps)
            if(i > 0):
                # add the time delay to all the times except for the first
                relative_time += time_delay
            # make sure all the times start relative to "start_t"
            times.append(relative_time + start_t)
        return times

    @staticmethod
    # TODO vectorize
    def gather_posn_data(ped_i, offset, swap_axes=False, scale_x=1, scale_y=1):
        xy_data = []
        xy_order = ('x', 'y')
        if(swap_axes):
            xy_order = ('y', 'x')
        # generate a list of lists of positions (only first variable)
        for p in ped_i[xy_order[0]]:
            scale = scale_y if xy_order[0] == 'y' else scale_x
            xy_data.append([scale * p])
        # append second variable to the list of positions
        for j, p in enumerate(ped_i[xy_order[1]]):
            scale = scale_x if xy_order[1] == 'x' else scale_y
            xy_data[j].append(scale * p)
        # apply the rotations to the x, y positions
        s = np.sin(offset[2])
        c = np.cos(offset[2])
        posn_data = []
        for (x, y) in xy_data:
            x_rot = x * c - y * s
            y_rot = x * s + y * c
            posn_data.append([x_rot + offset[0], y_rot + offset[1]])
        # append vector angles for all the agents
        for j, pos_2 in enumerate(posn_data):
            if j > 0:
                last_pos_2 = posn_data[j - 1]
                theta = np.arctan2(pos_2[1] - last_pos_2[1],
                                   pos_2[0] - last_pos_2[0])
                posn_data[j - 1].append(theta)
                # append same theta to the last position
                if j == len(posn_data) - 1:
                    # last element gets last angle
                    posn_data[j].append(theta)
        return posn_data

    @staticmethod
    def gather_posn_data_vec(ped_i, offset):
        xy_data = np.vstack([ped_i.x, ped_i.y]).T
        s = np.sin(offset[2])
        c = np.cos(offset[2])

        # apply the rotations to the x, y positions
        x_rot = xy_data[:, 0] * c - xy_data[:, 1] * s + offset[0]
        y_rot = xy_data[:, 0] * s + xy_data[:, 1] * c + offset[1]
        xy_rot = np.vstack([x_rot, y_rot]).T

        # append vector angles for all the agents
        xy_rot_diff = np.diff(xy_rot, axis=0)
        thetas = np.arctan2(xy_rot_diff[:, 1], xy_rot_diff[:, 0])
        thetas = np.hstack((thetas, thetas[-1]))
        xytheta = np.vstack((xy_rot.T, thetas)).T

        return xytheta

    @staticmethod
    def gather_vel_data(time_data, posn_data):
        # return linear speed to the list of variables
        v_data = []
        for j, pos_2 in enumerate(posn_data):
            if(j > 0):
                last_pos_2 = posn_data[j - 1]
                # calculating euclidean dist / delta_t
                delta_t = (time_data[j] - time_data[j - 1])
                speed = euclidean_dist2(pos_2, last_pos_2) / delta_t
                v_data.append(speed)  # last element gets last angle
            else:
                v_data.append(0)  # initial speed is 0
        return v_data

    @staticmethod
    def gather_vel_data_vec(time_data, posn_data):
        # return linear speed to the list of variables
        posn_data
        for j, pos_2 in enumerate(posn_data):
            if(j > 0):
                last_pos_2 = posn_data[j - 1]
                # calculating euclidean dist / delta_t
                delta_t = (time_data[j] - time_data[j - 1])
                speed = euclidean_dist2(pos_2, last_pos_2) / delta_t
                v_data.append(speed)  # last element gets last angle
            else:
                v_data.append(0)  # initial speed is 0
        return v_data

    @staticmethod
    def to_configs(xytheta_data, v_data):
        assert(len(xytheta_data) == len(v_data))
        config_data = []
        for i, pos3 in enumerate(xytheta_data):
            config_data.append(generate_config_from_pos_3(pos3, v=v_data[i]))
        return config_data

    @staticmethod
    def generate_pedestrians(simulator, params,
                             # default is ~1000 days (ie. no time bound)
                             max_time: int = 10e7,
                             pedestrian_dataset: DotMap = None
                             ):
        """"world_df" is a set of trajectories organized as a pandas dataframe.
            Each row is a pedestrian at a given frame (aka time point).
            The data was taken at 25 fps so between frames is 1/25th of a second. """
        import pandas as pd
        # gather metadata from pedestrian dataset
        csv_file = pedestrian_dataset.file_name
        offset = pedestrian_dataset.offset
        fps = pedestrian_dataset.fps
        start_t = pedestrian_dataset.start_t
        init_delay = pedestrian_dataset.spawn_delay_s
        start_idx = pedestrian_dataset.ped_range[0]
        max_agents = \
            -1 if pedestrian_dataset.ped_range[1] == -1 \
            else pedestrian_dataset.ped_range[1] - start_idx
        assert(fps > 0)
        swapxy = pedestrian_dataset.swapxy
        scale_x = -1 if pedestrian_dataset.flipxn else 1
        scale_y = -1 if pedestrian_dataset.flipyn else 1
        # run through the amount of agents
        if max_agents > 0 or max_agents == -1:
            datafile = \
                os.path.join(params.socnav_dir, "tests/datasets/", csv_file)
            world_df = pd.read_csv(datafile, header=None).T
            world_df.columns = ['frame', 'ped', 'y', 'x']
            world_df[['frame', 'ped']] = \
                world_df[['frame', 'ped']].astype('int')
            start_frame = world_df['frame'][0]  # default start (of data)
            all_peds = np.unique(world_df.ped)
            max_peds = max(all_peds)
            if max_agents == -1:
                max_agents = max_peds - 1
            for i in range(max_agents):
                ped_id = i + start_idx + 1
                if ped_id > max_peds:
                    print("%sRequested Prerec agent index out of bounds:" %
                          color_red, ped_id, "%s" % color_reset)
                if ped_id not in all_peds:
                    print("%sRequested agent %d not found in dataset: %s%s" %
                          (color_red, ped_id, csv_file, color_reset))
                    # this can happen based off the dataset
                    continue
                ped_i = world_df[world_df.ped == ped_id]
                # gather data
                if i == 0:
                    # update start frame to be representative of "first" pedestrian
                    start_frame = list(ped_i['frame'])[0]
                t_data = PrerecordedHuman.gather_times(ped_i, init_delay,
                                                       start_frame, start_t, fps)
                if t_data[0] > max_time:
                    # assuming the data of the agents is sorted relatively based off time
                    break
                print("Generating prerecorded agents %d to %d \r" %
                      (start_idx, ped_id), end="")
                xytheta_data = PrerecordedHuman.gather_posn_data(ped_i, offset,
                                                                 swap_axes=swapxy,
                                                                 scale_x=scale_x,
                                                                 scale_y=scale_y)
                v_data = PrerecordedHuman.gather_vel_data(t_data, xytheta_data)
                # combine the xytheta with the velocity
                config_data = PrerecordedHuman.to_configs(xytheta_data, v_data)
                new_agent = PrerecordedHuman(t_data=t_data, posn_data=config_data,
                                             generate_appearance=params.render_3D)
                simulator.add_agent(new_agent)
            # to not disturb the carriage-return print
            print()
