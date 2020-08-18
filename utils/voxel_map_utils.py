import numpy as np
import tensorflow as tf


class VoxelMap(object):
    """
    A voxel map object that allows to compute the function value at any arbitrary point in the voxel grid.
    """

    def __init__(self, scale, origin_2, map_size_2, function_array_mn):
        """
        Args:
            scale: The scale (dx) of the grid.
            origin_2: The origin of the voxel grid in the voxel space.
            map_size_2: The number of voxels in the voxel grid.
            function_array_mn: The function stored in the voxel grid. The size of the grid is assumed to be mxn, where
            m is the size in the y-dimension and n is in the x-dimension.
        """
        self.map_scale = np.array(scale, dtype=np.float32)
        self.map_origin_2 = origin_2
        self.map_size_int32_2 = map_size_2.astype(np.int32)
        self.map_size_float32_2 = map_size_2.astype(np.float32)
        self.voxel_function_mn = function_array_mn

    def compute_voxel_function(self, position_nk2, invalid_value=100.):
        """
        Compute the voxel function at the specified positions.
        """
        # Compute the position in the voxel space.
        voxel_space_position_nk2 = self.grid_world_to_voxel_world(
            position_nk2) - self.map_origin_2

        # Define the lower and upper voxels. Mod is done to make sure that the invalid voxels have been
        # assigned a valid voxel. However, these invalid voxels will be discarded later.
        lower_voxel_indices_nk2_xy = np.mod(
            np.floor(voxel_space_position_nk2).astype(np.int32), self.map_size_int32_2)
        upper_voxel_indices_nk2_xy = np.mod(
            lower_voxel_indices_nk2_xy + 1, self.map_size_int32_2)

        lower_voxel_float_nk2 = lower_voxel_indices_nk2_xy.astype(np.float32)
        upper_voxel_float_nk2 = upper_voxel_indices_nk2_xy.astype(np.float32)

        # Voxel indices for 4 corner voxels. Note that indices are stacked out of order for voxel_indices11 to make
        # sure that the first element along axis2 represents y-value (since the voxel map's first dimension is y and
        # not x).
        voxel_indices_nk4 = np.concatenate(
            [lower_voxel_indices_nk2_xy, upper_voxel_indices_nk2_xy], axis=2)

        # TODO: Casting as int64 because tfe.DEVICE_PLACEMENT_SILENT
        # is not working to place non-gpu ops (i.e. gather for (int32, int 32)) on
        # the cpu. This is potentially slowing things down as it copies to cpu
        voxel_indices_int64_nk4 = voxel_indices_nk4.astype(np.int64)

        def gather_nd2(params, indices):
            '''
            the input indices must be a 2d tensor in the form of [[a,b,..,c],...],
            which represents the location of the elements.
            '''
            # Normalize indices values
            params_size = list(params.shape)
            print(params_size, indices.shape[2])
            assert len(params_size) == indices.shape[2]

            indices[indices < 0] = 0
            for idx, ps in enumerate(params_size):
                indices[indices[:, idx] >= ps] = 0

            # Generate indices
            indices = np.transpose(indices)
            ndim = indices.shape[0]
            idx = np.zeros_like(indices[0])
            m = 1

            for i in range(ndim)[::-1]:
                idx += indices[i] * m
                m *= params.shape[i]

            return np.take(params, idx)

        def gather_nd(params, indices):
            """params is of "n" dimensions and has size [x1, x2, x3, ..., xn], indices is of 2 dimensions  and has size [num_samples, m] (m <= n)"""
            return params[indices.T]
        # Voxel function values at corner points
        data = self.voxel_function_mn
        indices_1 = np.take(voxel_indices_int64_nk4, [1, 0], axis=2)
        # data11_nk = np.take(data, indices_1.T)
        data11_nk = tf.gather_nd(data, indices_1)
        indices_2 = np.take(voxel_indices_int64_nk4, [1, 2], axis=2)
        # data21_nk = np.take(data, indices_2.T)
        data21_nk = tf.gather_nd(data, indices_2)
        indices_3 = np.take(voxel_indices_int64_nk4, [3, 0], axis=2)
        # data12_nk = np.take(data, indices_3.T)
        data12_nk = tf.gather_nd(data, indices_3)
        indices_4 = np.take(voxel_indices_int64_nk4, [3, 2], axis=2)
        # data22_nk = np.take(data, indices_4.T)
        data22_nk = tf.gather_nd(data, indices_4)

        # Define gammas for x interpolation
        gamma1 = upper_voxel_float_nk2[:, :, 0] - \
            voxel_space_position_nk2[:, :, 0]
        gamma2 = voxel_space_position_nk2[:, :,
                                          0] - lower_voxel_float_nk2[:, :, 0]

        # Define betas for y interpolation
        beta1 = upper_voxel_float_nk2[:, :, 1] - \
            voxel_space_position_nk2[:, :, 1]
        beta2 = voxel_space_position_nk2[:, :,
                                         1] - lower_voxel_float_nk2[:, :, 1]

        # Interpolation in the x-direction
        fx1_nk = gamma1 * data11_nk + gamma2 * data21_nk
        fx2_nk = gamma1 * data12_nk + gamma2 * data22_nk

        # Interpolation in the y-direction
        f_nk = beta1 * fx1_nk + beta2 * fx2_nk

        # Discard the invalid voxels
        valid_voxels_nk = self.is_valid_voxel(position_nk2)

        return np.where(valid_voxels_nk, f_nk, np.ones_like(f_nk) * invalid_value)

    def grid_world_to_voxel_world(self, position_nk2):
        """
        Convert the positions in the global world to the voxel world coordinates.
        """
        return position_nk2 / self.map_scale

    def is_valid_voxel(self, position_nk2):
        """
        Check if a given set of positions are within the voxel map or not.

        """
        voxel_space_position_nk2 = self.grid_world_to_voxel_world(
            position_nk2) - self.map_origin_2
        return np.logical_and(np.all(voxel_space_position_nk2 >= 0., axis=2),
                              np.all(voxel_space_position_nk2 < (self.map_size_float32_2 - 1.), axis=2))
