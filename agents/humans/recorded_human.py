from utils.utils import generate_config_from_pos_3, euclidean_dist2
from utils.utils import color_red, color_reset
import os
from agents.humans.human import Human
from agents.humans.human_configs import HumanConfigs
from agents.humans.human_appearance import HumanAppearance
from agents.agent import Agent
import numpy as np
import scipy


class PrerecordedHuman(Human):
    def __init__(self, t_data, posn_data, interps, generate_appearance=True, name=None):
        assert(len(t_data) == len(posn_data))
        self.t_data = t_data
        # useful to know the ground truth pedestrian data rate
        self.del_t = t_data[2] - t_data[1]
        self.posn_data = posn_data
        self.current_step = 0
        self.current_precalc_step = 0
        self.current_config = self.posn_data[0]
        self.next_step = self.posn_data[1]
        self.world_state = None
        self.xinterp, self.yinterp, self.thinterp = interps
        init_configs = HumanConfigs(posn_data[0], posn_data[-1])
        if generate_appearance:
            appearance = HumanAppearance.generate_random_human_appearance(
                HumanAppearance)
        else:
            appearance = None
        self.relative_diff: float = 0.0  # how much time the agent will spend stopped
        super().__init__(name, appearance, init_configs)

    def get_start_time(self):
        return self.t_data[0]

    def get_end_time(self):
        return self.t_data[-1]

    def get_current_time(self):
        return self.t_data[self.current_precalc_step]

    def get_rel_t(self):
        # agent might've spent some time still (after a collision)
        # and must account for that given the world clock (Agent.sim_t)
        return Agent.sim_t - self.relative_diff * Agent.sim_dt

    def get_completed(self):
        # dont have special termination conditions
        # only care about the time not surpassing max t_data
        self.end_acting = (self.get_rel_t() < self.get_end_time())
        return self.get_rel_t() < self.get_end_time()

    def get_interp_posns(self):
        x = self.xinterp(self.get_rel_t())
        y = self.yinterp(self.get_rel_t())
        t = self.current_precalc_step
        prev_x, prev_y, prev_theta = \
            np.squeeze(self.posn_data[t].position_and_heading_nk3())
        _, _, next_theta = \
            np.squeeze(self.posn_data[t + 1].position_and_heading_nk3())
        # TODO: fix bug where interpolated points VERY close to the previous points
        # result in numerical errors that result in incorrect theta calculations
        theta = np.arctan2((y - prev_y), (x - prev_x))
        avg_theta = np.mean([prev_theta, next_theta])
        if np.abs(theta - avg_theta) > 0.5:  # TODO: Magic number! ... bad!
            theta = avg_theta
        # construct interpolated position
        posn_interp = [x, y, theta]
        last_t = np.floor((self.get_rel_t() - self.t_data[0]) / Agent.sim_dt)
        last_non_interp_v = np.squeeze(self.posn_data[int(last_t)].speed_nk1())
        posn_interp_conf = generate_config_from_pos_3(posn_interp,
                                                      v=last_non_interp_v)
        return posn_interp_conf

    def sense(self, sim_state):
        self.update_world(sim_state)
        if self.check_collisions(self.world_state, include_agents=False):
            self.collision_cooldown = self.params.collision_cooldown_amnt
            # only pause the agents if flag is set
            if self.params.pause_on_collide:
                # update relative time differences
                self.relative_diff += self.collision_cooldown
        # update collision cooldown
        if(self.collision_cooldown > 0):
            self.collision_cooldown -= 1

    def plan(self):
        # TODO now this step is performed in one go - what does this mean for collisions?
        # while not self.has_collided and self.get_rel_t() > self.get_current_time():
        # this is to account for the delay_time / init_delay
        if self.params.pause_on_collide and self.collision_cooldown > 0:
            return
        self.current_precalc_step = \
            int((self.get_rel_t() - self.t_data[1] + self.del_t) / self.del_t)

    def act(self):
        if self.params.pause_on_collide and self.collision_cooldown > 0:
            return
        self.current_step += 1
        self.current_config = self.get_interp_posns()
        # append current config to trajectory
        self.trajectory.append_along_time_axis(self.current_config)

    def update(self, sim_state=None):
        self.sense(sim_state)
        self.plan()
        self.act()

    def end(self):
        """Teleport the agents to the last step in their trajectory"""
        self.set_current_config(self.goal_config)

    """ BEGIN INITIALIZATION UTILS """

    @staticmethod
    def init_interp_fns(posn_data, times):
        posn_data = np.array(posn_data)
        ts = np.array(times)
        # correct for the fact that times of 0 is weird
        ts[0] = ts[1] - (ts[2] - ts[1])

        x = posn_data[:, 0]
        y = posn_data[:, 1]
        th = posn_data[:, 2]
        interp = scipy.interpolate.interp1d
        xfunc = interp(ts, x, bounds_error=False, fill_value=(x[0], x[-1]))
        yfunc = interp(ts, y, bounds_error=False, fill_value=(y[0], y[-1]))
        thfunc = interp(ts, th, bounds_error=False, fill_value=(th[0], th[-1]))
        return xfunc, yfunc, thfunc

    @staticmethod
    def gather_times(ped_i, time_delay: float, start_t: float, start_frame: int, fps: float):
        times = (ped_i['frame'] - start_frame) * (1. / fps)
        # account for the time delay (before the rest of the action),
        # and the start time (when the pedestrian first appears in the simulator)
        times += time_delay + start_t
        # convert pd df column to list
        times = list(times)
        # add the first time step (after spawning, before moving)
        times = [times[0] - start_t] + times
        return times

    @staticmethod
    def gather_posn_data(ped_i, offset, swap_axes=False, scale_x=1, scale_y=1):
        xy_data = []
        xy_order = ('x', 'y')
        scale = (scale_x, scale_y)
        if swap_axes:
            xy_order = ('y', 'x')
            scale = (scale_y, scale_x)
        # gather the data from df
        xy_data = np.array([scale[0] * ped_i[xy_order[0]],
                            scale[1] * ped_i[xy_order[1]]])
        # apply the rotations to the x, y positions
        s = np.sin(offset[2])
        c = np.cos(offset[2])
        # construct xy data
        posn_data = np.array([xy_data[0] * c - xy_data[1] * s + offset[0],
                              xy_data[0] * s + xy_data[1] * c + offset[1]])
        # append vector angles for all the agents
        now = posn_data[:, 1:]  # skip first
        last = posn_data[:, :-1]  # skip last
        thetas = np.arctan2(now[1] - last[1], now[0] - last[0])
        thetas = np.append(thetas, thetas[-1])  # last element gets last angle
        assert(len(thetas) == len(posn_data.T))
        # append thetas to posn data
        posn_data = np.vstack([posn_data, thetas.T]).T
        # add the first position to the start of the data for the initial delay
        posn_data = np.insert(posn_data, [0], posn_data[0], axis=0)
        return posn_data

    @staticmethod
    def gather_posn_data_vec(ped_i, offset):
        # old vectorized function for experimentation
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

        return [xytheta[0]] + xytheta

    @staticmethod
    def gather_vel_data(time_data, posn_data):
        # return linear speed to the list of variables
        v_data = []
        assert(len(time_data) == len(posn_data))
        for j, pos_2 in enumerate(posn_data):
            if(j > 1):
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
    def generate(simulator, params, environment, renderer, max_time=10e7,
                 start_t=0, ped_range=(0, -1), dataset=None):
        """"world_df" is a set of trajectories organized as a pandas dataframe.
            Each row is a pedestrian at a given frame (aka time point).
            The data was taken at 25 fps so between frames is 1/25th of a second. """
        import pandas as pd
        # gather metadata from pedestrian dataset
        csv_file = dataset.file_name
        offset = dataset.offset
        fps = dataset.fps
        spawn_delay_s = dataset.spawn_delay_s
        start_idx = ped_range[0]  # start index
        max_agents = -1 if ped_range[1] == -1 \
            else ped_range[1] - start_idx
        assert(fps > 0)
        swapxy = dataset.swapxy
        scale_x = -1 if dataset.flipxn else 1
        scale_y = -1 if dataset.flipyn else 1
        # run through the amount of agents
        if ped_range[0] == ped_range[1]:  # have an empty range
            return
        datafile = \
            os.path.join(params.socnav_dir, params.dataset_dir, csv_file)
        print("Generating pedestrians from \"%s\" in range [%d, %d]\r" %
              (dataset.name, ped_range[0], ped_range[1]), end="")
        world_df = pd.read_csv(datafile, header=None).T
        world_df.columns = ['frame', 'ped', 'y', 'x']
        world_df[['frame', 'ped']] = \
            world_df[['frame', 'ped']].astype('int')
        start_frame = world_df['frame'][0]  # default start (of data)
        all_peds = np.unique(world_df.ped)
        max_peds = max(all_peds)
        if max_agents == -1:
            # set to all pedestrians
            max_agents = max_peds - 1
        # ensure that max_agents never goes out of bounds
        max_agents = min(max_agents, max_peds)
        for i in range(max_agents):
            ped_id = i + start_idx + 1
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
            t_data = PrerecordedHuman.gather_times(ped_i, spawn_delay_s, start_t,
                                                   start_frame, fps)
            if (ped_i.frame.iloc[0] - start_frame) / fps > max_time:
                # assuming the data of the agents is sorted relatively based off time
                break
            print("Generating pedestrians from \"%s\" in range [%d, %d]: %d\r" %
                  (dataset.name, ped_range[0], ped_range[1], ped_id), end="")
            xytheta_data = PrerecordedHuman.gather_posn_data(ped_i, offset,
                                                             swap_axes=swapxy,
                                                             scale_x=scale_x,
                                                             scale_y=scale_y)
            interp_fns = PrerecordedHuman.init_interp_fns(xytheta_data,
                                                          t_data)

            v_data = PrerecordedHuman.gather_vel_data(t_data, xytheta_data)
            # combine the xytheta with the velocity
            config_data = PrerecordedHuman.to_configs(xytheta_data, v_data)
            name = "prerec_%04d" % (i)
            new_agent = PrerecordedHuman(t_data=t_data, posn_data=config_data,
                                         generate_appearance=params.render_3D,
                                         interps=interp_fns, name=name)
            simulator.add_agent(new_agent)

            # add human to renderer
            # TODO: make sure this works
            if params.render_3D:
                renderer.add_human(new_agent)
                environment["human_traversible"] = \
                    np.array(renderer.get_human_traversible())
        # to not disturb the carriage-return print
        print()
