import numpy as np
from metrics import cost_functions
from simulators.central_simulator import CentralSimulator


# meta
def success(central_sim: CentralSimulator):
    terminate_cause = central_sim.robot.termination_cause
    if terminate_cause == "Collision":
        return False
    elif terminate_cause == "Timeout":
        return False
    elif terminate_cause == "Success":
        return True
    else:
        print(terminate_cause)
        raise ValueError("Unexpected robot termination_cause must be one of Collided/Timeout/Success")
    return False


def total_sim_time_taken(central_sim: CentralSimulator):
    last_step_num = max(list(central_sim.states.keys()))
    return last_step_num * central_sim.delta_t


def sim_time_budget(central_sim: CentralSimulator):
    return central_sim.episode_params.max_time


def termination_cause(central_sim: CentralSimulator):
    return central_sim.robot.termination_cause


def wall_wait_time(central_sim: CentralSimulator):
    return central_sim.robot.get_block_t_total()


# motion
def robot_speed(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    delta_t = central_sim.delta_t
    robot_displacement = np.diff(robot_trajectory, axis=0)
    robot_speed = np.sqrt((robot_displacement[:, 0]/delta_t)**2 + (robot_displacement[:, 1]/delta_t)**2)

    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_speed


def robot_velocity(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    delta_t = central_sim.delta_t
    robot_displacement = np.diff(robot_trajectory, axis=0)
    robot_vel = robot_displacement/delta_t

    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_vel


def robot_acceleration(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    delta_t = central_sim.delta_t
    robot_displacement = np.diff(robot_trajectory, axis=0)
    robot_vel = robot_displacement/delta_t
    robot_acc = np.diff(robot_vel, axis=0)/delta_t

    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_acc


def robot_jerk(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    delta_t = central_sim.delta_t
    robot_vel = np.diff(robot_trajectory, axis=0) / delta_t
    robot_acc = np.diff(robot_vel, axis=0) / delta_t
    robot_jrk = np.diff(robot_acc, axis=0) / delta_t

    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_jrk


def robot_motion_energy(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    delta_t = central_sim.delta_t
    robot_displacement = np.diff(robot_trajectory, axis=0)
    robot_motion_energy = np.sum((robot_displacement[:, 0]/delta_t)**2 + (robot_displacement[:, 1]/delta_t)**2)

    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_motion_energy


# path
def path_length(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    robot_goal = np.squeeze(central_sim.robot.goal_config.position_and_heading_nk3())[:-1]
    robot_path_ln = cost_functions.path_length(robot_trajectory)
    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_path_ln


def path_length_ratio(central_sim: CentralSimulator, percentile=False):
    # extract the bot traj and drop the heading
    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    robot_goal = np.squeeze(central_sim.robot.goal_config.position_and_heading_nk3())[:-1]
    robot_path_ln_ratio = cost_functions.path_length_ratio(robot_trajectory, goal_config=robot_goal)
    if percentile:
        # TODO run for all peds
        df = central_sim.sim_df
        pass
    return robot_path_ln_ratio


def path_irregularity(central_sim: CentralSimulator, percentile=False):

    robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())
    # check if goal was reached
    if central_sim.robot.termination_cause == "Success":
        path_irr = cost_functions.path_irregularity(
            trajectory=robot_trajectory
        )
    else:
        goal = central_sim.robot.get_goal_config().to_3D_numpy()
        path_irr = cost_functions.path_irregularity(
            trajectory=robot_trajectory,
            goal_config=goal
        )

    if percentile:
        # TODO run for all
        df = central_sim.sim_df
        pass
    return path_irr


# pedestrian related
def time_to_collision(central_sim: CentralSimulator, percentile=False):
    sim_df = central_sim.sim_df
    robot_indcs = (sim_df.agent_name == 'robot_agent')
    ped_df = central_sim.sim_df[~robot_indcs]
    bot_df = central_sim.sim_df[robot_indcs]
    robot_trajectory = np.vstack([bot_df.x, bot_df.y, bot_df.theta]).T

    delta_t = central_sim.delta_t
    robot_displacement = np.diff(robot_trajectory, axis=0)
    robot_inst_vel = robot_displacement / delta_t
    robot_df = ped_df[ped_df.agent_name == 'robot_agent']

    # for each time instance in which robot_trajectory exists
    ttc = np.zeros((len(robot_inst_vel)))
    for sim_step in range(len(robot_inst_vel)):
        sim_step += 1  # velocity is valid only after 2 steps
        # for each bot-ped pair
        # compute the robot-pedestrian relative velocity at each instant
        ped_inst = ped_df[ped_df.sim_step == sim_step]
        ped_prev = ped_df[ped_df.sim_step == sim_step-1]
        ped_inst_posns = np.vstack([ped_inst.x, ped_inst.y])
        ped_prev_posns = np.vstack([ped_prev.x, ped_prev.y])
        ped_inst_vels = (ped_inst_posns - ped_prev_posns)/central_sim.delta_t

        botped_relative_vels = ped_inst_vels - robot_inst_vel

        # compute the robot-pedestrian joining unit vector
        botped_vectors = robot_trajectory[sim_step, :] - ped_inst_posns
        botped_distances = np.linalg.norm(botped_vectors, axis=1)
        # needs the extra axis to divide correctly
        botped_uvectors = botped_vectors / np.linalg.norm(botped_vectors)[:, None]

        # take relative velocity component along the joining vector
        botped_component = np.sum(botped_relative_vels * botped_uvectors, axis=1)

        # see how long it would take to cover that distance w relative velocity
        ttc_all = botped_distances / botped_component
        ttc_pos = ttc_all[ttc_all > 0]  # discard negative times
        ttc[sim_step-1] = np.min(ttc_pos)

    return ttc


def closest_pedestrian_distance(central_sim: CentralSimulator, percentile=False):
    sim_df = central_sim.sim_df
    robot_indcs = (sim_df.agent_name == 'robot_agent')
    ped_df = central_sim.sim_df[~robot_indcs]
    bot_df = central_sim.sim_df[robot_indcs]
    robot_trajectory = np.vstack([bot_df.x, bot_df.y]).T
    # robot_trajectory = np.squeeze(central_sim.robot.vehicle_trajectory.position_and_heading_nk3())[:, :-1]
    delta_t = central_sim.delta_t

    cpd = np.zeros((len(robot_trajectory)))
    for sim_step in range(len(robot_trajectory)):
        ped_inst = ped_df[ped_df.sim_step == sim_step]
        # compute the robot-pedestrian joining unit vector
        ped_inst_posns = np.vstack([ped_inst.x, ped_inst.y]).T
        botped_vectors = robot_trajectory[sim_step] - ped_inst_posns
        botped_distances = np.linalg.norm(botped_vectors, axis=1)
        cpd[sim_step] = np.min(botped_distances)

    return cpd