from __future__ import print_function
from builtins import str
from builtins import range

import set_pyreg_paths

import matplotlib as matplt
from pyreg.config_parser import MATPLOTLIB_AGG
#if MATPLOTLIB_AGG:
#    matplt.use('Agg')

import matplotlib.pyplot as plt
import scipy.ndimage as ndimage

import pyreg.utils as utils
import pyreg.finite_differences as fd
import pyreg.custom_pytorch_extensions as ce
import pyreg.smoother_factory as sf

from pyreg.data_wrapper import AdaptVal

import pyreg.fileio as fio

import pyreg.rungekutta_integrators as rk
import pyreg.forward_models as fm

import pyreg.module_parameters as pars

import torch
from torch.autograd import Variable

import numpy as np

import os
import random

def subsampled_quiver(u,v,color='red', scale=1, subsample=3):
    sz = u.shape
    xc,yc = np.meshgrid(range(sz[0]),range(sz[1]))
    plt.quiver(xc[::subsample,::subsample],yc[::subsample,::subsample],u[::subsample,::subsample], v[::subsample,::subsample], color=color, scale=scale)


def create_momentum(input_im,centered_map,
                    randomize_momentum_on_circle,randomize_in_sectors,
                    smooth_initial_momentum,
                    sz,spacing,nr_of_angles=10,multiplier_factor=1.0,momentum_smoothing=0.05,visualize=False,
                    publication_figures_directory=None,
                    publication_prefix=None,
                    image_pair_nr=None):

    # assumes an input image is given (at least roughly centered in the middle of the image)
    # and computes a random momentum

    fd_np = fd.FD_np(spacing)
    # finite differences expect BxXxYxZ (without image channel)

    # gradients for the input image (to determine where the edges are)
    dxc = fd_np.dXc(input_im[:, 0, ...])
    dyc = fd_np.dYc(input_im[:, 0, ...])

    # compute the current distance map (relative to the center)
    dist_map = (centered_map[:, 0, ...] ** 2 + centered_map[:, 1, ...] ** 2) ** 0.5
    # gradients for the distance map (to get directions)
    dxc_d = fd_np.dXc(dist_map)
    dyc_d = fd_np.dYc(dist_map)

    # zero them out everywhere, where the input image does not have a gradient
    ind_zero = (dxc ** 2 + dyc ** 2 == 0)
    dxc_d[ind_zero] = 0
    dyc_d[ind_zero] = 0

    #plt.clf()
    #plt.quiver(dyc_d[0,...],dxc_d[0,...],scale=5)
    #plt.show()

    # and now randomly flip the sign ring by ring
    maxr = int(input_im.max())

    # identity map to define the sectors
    id_c = utils.centered_identity_map_multiN(sz, spacing, dtype='float32')

    already_flipped = np.zeros_like(dxc_d)

    for r in range(1,maxr+1):

        cur_ring_val = r

        if randomize_momentum_on_circle:

            randomize_over_angles = randomize_in_sectors

            if randomize_over_angles:
                angles = np.sort(2 * np.pi * np.random.rand(nr_of_angles))

                for a in range(nr_of_angles):
                    afrom = a
                    ato = (a + 1) % nr_of_angles

                    nx_from = -np.sin(angles[afrom])
                    ny_from = np.cos(angles[afrom])

                    nx_to = -np.sin(angles[ato])
                    ny_to = np.cos(angles[ato])

                    dilated_input_im = ndimage.binary_dilation(input_im[:,0,...]==cur_ring_val)

                    indx = ((dilated_input_im!=0) & (already_flipped==0) & (dxc ** 2 + dyc ** 2 != 0)
                            & (id_c[:, 0, ...] * nx_from + id_c[:, 1, ...] * ny_from >= 0)
                            & (id_c[:, 0, ...] * nx_to + id_c[:, 1, ...] * ny_to < 0))

                    c_rand_choice = np.random.randint(0, 3)
                    if c_rand_choice == 0:
                        multiplier = multiplier_factor
                    elif c_rand_choice == 1:
                        multiplier = 0.0
                    else:
                        multiplier = -multiplier_factor

                    c_rand_val_field = multiplier * np.random.rand(*list(indx.shape))

                    dxc_d[indx] = dxc_d[indx] * c_rand_val_field[indx]
                    dyc_d[indx] = dyc_d[indx] * c_rand_val_field[indx]

                    already_flipped[indx] = 1

                    #print(c_rand_choice)
                    #plt.clf()
                    #plt.subplot(121)
                    #plt.quiver(dyc_d[0, ...], dxc_d[0, ...], scale=5)
                    #plt.subplot(122)
                    #plt.imshow(indx[0,...])
                    #plt.show()

            else:
                dilated_input_im = ndimage.binary_dilation(input_im[:, 0, ...] == cur_ring_val)

                indx = ((dilated_input_im!=0) & (already_flipped==0) & (dxc ** 2 + dyc ** 2 != 0))
                already_flipped[indx] = 1
                c_rand_val_field = 2 * 2 * (np.random.rand(*list(indx.shape)) - 0.5)

                dxc_d[indx] = dxc_d[indx] * c_rand_val_field[indx]
                dyc_d[indx] = dyc_d[indx] * c_rand_val_field[indx]

        else:
            dilated_input_im = ndimage.binary_dilation(input_im[:, 0, ...] == cur_ring_val)

            indx = ((dilated_input_im!=0) & (already_flipped==0) & (dxc ** 2 + dyc ** 2 != 0))
            already_flipped[indx] = 1

            # multiply by a random number in [-1,1]
            c_rand_val = 2 * (np.random.rand() - 0.5)*multiplier_factor

            dxc_d[indx] = dxc_d[indx] * c_rand_val
            dyc_d[indx] = dyc_d[indx] * c_rand_val

    # now create desired initial momentum
    m_orig = np.zeros_like(id_c)
    m_orig[0, 0, ...] = dxc_d
    m_orig[0, 1, ...] = dyc_d

    if visualize:
        plt.clf()
        plt.quiver(m_orig[0, 1, ...], m_orig[0, 0, ...],color='red',scale=5)
        plt.axis('equal')
        plt.show()

    if publication_figures_directory is not None:

        plt.clf()
        plt.imshow(input_im[0, 0, ...],origin='lower')
        plt.quiver(m_orig[0, 1, ...], m_orig[0, 0, ...],color='red',scale=5)
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory, '{:s}_m_orig_{:d}.pdf'.format(publication_prefix,image_pair_nr)),bbox_inches='tight',pad_inches=0)

    if smooth_initial_momentum:
        s_m_params = pars.ParameterDict()
        s_m_params['smoother']['type'] = 'gaussian'
        s_m_params['smoother']['gaussian_std'] = momentum_smoothing
        s_m = sf.SmootherFactory(sz[2::], spacing).create_smoother(s_m_params)

        m = s_m.smooth(AdaptVal(Variable(torch.from_numpy(m_orig), requires_grad=False))).data.cpu().numpy()

        if visualize:
            plt.clf()
            plt.subplot(121)
            plt.imshow(m_orig[0, 0, ...])
            plt.subplot(122)
            plt.imshow(m[0, 0, ...])
            plt.suptitle('smoothed mx')
            plt.show()

        if publication_figures_directory is not None:
            plt.clf()
            plt.imshow(input_im[0,0,...],origin='lower')
            subsampled_quiver(m[0, 1, ...], m[0, 0, ...], color='red', scale=1,subsample=3)
            plt.axis('image')
            plt.axis('off')
            plt.savefig(os.path.join(publication_figures_directory, '{:s}_m_smoothed_orig_{:d}.pdf'.format(publication_prefix,image_pair_nr)),bbox_inches='tight')

    else:
        m = m_orig

    return m

def compute_overall_std(weights,multi_gaussian_stds):

    # standard deviation image (only for visualization; this is the desired ground truth)
    sh_std_im = weights.shape[2:]
    std_im = np.zeros(sh_std_im, dtype='float32')
    nr_of_mg_weights = weights.shape[1]

    # now compute the resulting standard deviation image (based on the computed weights)
    for g in range(nr_of_mg_weights):
        std_im += weights[0,g,...]*multi_gaussian_stds[g]**2

    std_im = std_im**0.5

    return std_im


def create_rings(levels_in,multi_gaussian_weights,default_multi_gaussian_weights,
                 multi_gaussian_stds,put_weights_between_circles,
                 sz,spacing,visualize=False):

    if len(multi_gaussian_weights)+1!=len(levels_in):
        raise ValueError('There needs to be one more level than the number of weights, to define this example')

    id_c = utils.centered_identity_map_multiN(sz, spacing, dtype='float32')
    sh_id_c = id_c.shape

    # create the weights that will be used for the multi-Gaussian
    nr_of_mg_weights = len(default_multi_gaussian_weights)
    # format for weights: B x nr_gaussians x X x Y x Z
    sh_weights = [sh_id_c[0]] + [nr_of_mg_weights] + list(sh_id_c[2:])

    weights = np.zeros(sh_weights,dtype='float32')
    # set the default
    for g in range(nr_of_mg_weights):
        weights[:,g,...] = default_multi_gaussian_weights[g]

    # now get the memory for the ring data
    sh_ring_im = list(sh_id_c[2:])
    ring_im = np.zeros(sh_ring_im,dtype='float32')

    # just add one more level in case we put weights in between (otherwise add a dummy)
    levels = np.zeros(len(levels_in)+1)
    levels[0:-1] = levels_in
    if put_weights_between_circles:
        levels[-1] = levels_in[-1]+levels_in[-1]-levels_in[-2]
    else:
        levels[-1]=-1.

    for i in range(len(levels)-2):
        cl = levels[i]
        nl = levels[i+1]
        nnl = levels[i+2]
        cval = i+1

        indices_ring = (id_c[0,0,...]**2+id_c[0,1,...]**2>=cl**2) & (id_c[0,0,...]**2+id_c[0,1,...]**2<=nl**2)
        ring_im[indices_ring] = cval

        # as the momenta will be supported on the ring boundaries, we may want the smoothing to be changing in the middle of the rings
        if put_weights_between_circles:
            indices_weight = (id_c[0,0,...]**2+id_c[0,1,...]**2>=((cl+nl)/2)**2) & (id_c[0,0,...]**2+id_c[0,1,...]**2<=((nl+nnl)/2)**2)
        else:
            indices_weight = (id_c[0, 0, ...] ** 2 + id_c[0, 1, ...] ** 2 >= cl ** 2) & (id_c[0, 0, ...] ** 2 + id_c[0, 1, ...] ** 2 <= nl ** 2)

        # set the desired weights in this ring
        current_desired_weights = multi_gaussian_weights[i]
        for g in range(nr_of_mg_weights):
            current_weights = weights[0,g,...]
            current_weights[indices_weight] = current_desired_weights[g]

    std_im = compute_overall_std(weights,multi_gaussian_stds)
    ring_im = ring_im.view().reshape([1,1] + sh_ring_im)

    if visualize:

        #grad_norm_sqr = dxc**2 + dyc**2

        plt.clf()
        plt.subplot(221)
        plt.imshow(id_c[0, 0, ...])
        plt.colorbar()
        plt.subplot(222)
        plt.imshow(id_c[0, 1, ...])
        plt.colorbar()
        plt.subplot(223)
        plt.imshow(ring_im[0,0,...])
        plt.colorbar()
        plt.subplot(224)
        #plt.imshow(grad_norm_sqr[0,...]>0)
        #plt.colorbar()

        plt.show()

        plt.clf()

        nr_of_weights = weights.shape[1]

        for cw in range(nr_of_weights):
            plt.subplot(2,3,1+nr_of_weights)
            plt.imshow(weights[0,cw,...],vmin=0.0,vmax=1.0)
            plt.colorbar()

        plt.subplot(236)
        plt.imshow(std_im)
        plt.colorbar()
        plt.suptitle('weights')
        plt.show()


    return weights,ring_im,std_im


def _compute_ring_radii(extent, nr_of_rings, randomize_radii, randomize_factor=0.75):
    if randomize_radii:
        rings_at_default = np.linspace(0., extent, nr_of_rings + 1)
        diff_r = rings_at_default[1] - rings_at_default[0]
        rings_at = np.sort(rings_at_default + (np.random.random(nr_of_rings + 1) - 0.5) * diff_r * randomize_factor)
    else:
        rings_at = np.linspace(0., extent, nr_of_rings + 2)
    # first one needs to be zero:
    rings_at[0] = 0

    return rings_at

def compute_localized_velocity_from_momentum(m,weights,multi_gaussian_stds,sz,spacing,visualize=False):

    nr_of_gaussians = len(multi_gaussian_stds)
    # create a velocity field from this momentum using a multi-Gaussian kernel
    gaussian_fourier_filter_generator = ce.GaussianFourierFilterGenerator(sz[2:], spacing, nr_of_gaussians)

    vs = ce.fourier_set_of_gaussian_convolutions(AdaptVal(Variable(torch.from_numpy(m), requires_grad=False)),
                                                 gaussian_fourier_filter_generator,
                                                 sigma=AdaptVal(Variable(torch.from_numpy(multi_gaussian_stds),
                                                                         requires_grad=False)),
                                                 compute_std_gradients=False)

    # compute velocity based on localized weights
    localized_v = np.zeros([1, 2] + sz[2:], dtype='float32')
    dims = localized_v.shape[1]
    for g in range(nr_of_gaussians):
        for d in range(dims):
            localized_v[0, d, ...] += weights[0, g, ...] * vs[g, 0, d, ...].data.cpu().numpy()

    if visualize:

        norm_localized_v = (localized_v[0, 0, ...] ** 2 + localized_v[0, 1, ...] ** 2) ** 0.5

        plt.clf()
        plt.subplot(121)
        plt.imshow(norm_localized_v)
        plt.axis('image')
        plt.colorbar()
        plt.subplot(121)
        plt.quiver(m[0,1,...],m[0,0,...])
        plt.axis('equal')
        plt.show()

    return localized_v

def compute_map_from_v(localized_v,sz,spacing):

    # now compute the deformation that belongs to this velocity field

    params = pars.ParameterDict()
    params['number_of_time_steps'] = 40

    advectionMap = fm.AdvectMap( sz[2:], spacing )
    pars_to_pass = utils.combine_dict({'v':AdaptVal(Variable(torch.from_numpy(localized_v),requires_grad=False))}, dict() )
    integrator = rk.RK4(advectionMap.f, advectionMap.u, pars_to_pass, params)

    tFrom = 0.
    tTo = 1.

    phi0 = AdaptVal(Variable(torch.from_numpy(utils.identity_map_multiN(sz,spacing)),requires_grad=False))
    phi1 = integrator.solve([phi0], tFrom, tTo )[0]

    return phi0,phi1

def add_texture(im_orig):
    sz = im_orig.shape
    rand_noise = np.random.random(sz[2:])
    rand_noise = rand_noise.view().reshape(sz)
    r_params = pars.ParameterDict()
    r_params['smoother']['type'] = 'gaussian'
    r_params['smoother']['gaussian_std'] = 0.015
    s_r = sf.SmootherFactory(sz[2::], spacing).create_smoother(r_params)

    rand_noise_smoothed = s_r.smooth(AdaptVal(Variable(torch.from_numpy(rand_noise), requires_grad=False))).data.cpu().numpy()
    rand_noise_smoothed /= rand_noise_smoothed.max()

    im = im_orig + rand_noise_smoothed

    return im

def create_random_image_pair(weights_not_fluid,weights_fluid,weights_neutral,weight_smoothing_std,multi_gaussian_stds,
                             randomize_momentum_on_circle,randomize_in_sectors,
                             put_weights_between_circles,
                             start_with_fluid_weight,
                             use_random_source,
                             nr_of_circles_to_generate,
                             circle_extent,
                             sz,spacing,
                             nr_of_angles=10,multiplier_factor=1.0,momentum_smoothing=0.05,
                             visualize=False,visualize_warped=False,print_warped_name=None,
                             publication_figures_directory=None,
                             image_pair_nr=None):

    nr_of_rings = nr_of_circles_to_generate
    extent = circle_extent
    randomize_factor = 0.25
    randomize_radii = True
    smooth_initial_momentum = True
    add_texture_to_image = True

    # create ordered set of weights
    multi_gaussian_weights = []

    for r in range(nr_of_rings):
        if r%2==0:
            if start_with_fluid_weight:
                multi_gaussian_weights.append(weights_fluid)
            else:
                multi_gaussian_weights.append(weights_not_fluid)
        else:
            if start_with_fluid_weight:
                multi_gaussian_weights.append(weights_not_fluid)
            else:
                multi_gaussian_weights.append(weights_fluid)


    rings_at = _compute_ring_radii(extent=extent, nr_of_rings=nr_of_rings, randomize_radii=randomize_radii, randomize_factor=randomize_factor)

    weights_orig,ring_im_orig,std_im_orig = create_rings(rings_at,multi_gaussian_weights=multi_gaussian_weights,
                    default_multi_gaussian_weights=weights_neutral,
                    multi_gaussian_stds=multi_gaussian_stds,
                    put_weights_between_circles=put_weights_between_circles,
                    sz=sz,spacing=spacing,
                    visualize=visualize)

    if weight_smoothing_std is not None:
        if weight_smoothing_std>0:
            s_m_params = pars.ParameterDict()
            s_m_params['smoother']['type'] = 'gaussian'
            s_m_params['smoother']['gaussian_std'] = weight_smoothing_std
            # smooth the weights
            smoother = sf.SmootherFactory(weights_orig.shape[2::], spacing).create_smoother(s_m_params)
            #weights_old = np.zeros_like(weights_orig)
            #weights_old[:] = weights_orig
            weights_orig = (smoother.smooth(Variable(torch.from_numpy(weights_orig),requires_grad=False))).data.cpu().numpy()

    if publication_figures_directory is not None:
        plt.clf()
        plt.imshow(ring_im_orig[0,0,...],origin='lower')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory,'ring_im_orig_{:d}.pdf'.format(image_pair_nr)),bbox_inches='tight',pad_inches=0)

        plt.clf()
        plt.imshow(std_im_orig,origin='lower')
        plt.axis('off')
        plt.colorbar()
        plt.savefig(os.path.join(publication_figures_directory,'std_im_orig_{:d}.pdf'.format(image_pair_nr)),bbox_inches='tight',pad_inches=0)


    id_c = utils.centered_identity_map_multiN(sz, spacing, dtype='float32')
    m_orig = create_momentum(ring_im_orig, centered_map=id_c, randomize_momentum_on_circle=randomize_momentum_on_circle,
                        randomize_in_sectors=randomize_in_sectors,
                        smooth_initial_momentum=smooth_initial_momentum,
                        sz=sz, spacing=spacing,
                        nr_of_angles=nr_of_angles,
                        multiplier_factor=multiplier_factor,
                        momentum_smoothing=momentum_smoothing,
                        publication_figures_directory=publication_figures_directory,
                        publication_prefix='circle_init',
                        image_pair_nr=image_pair_nr)

    localized_v_orig = compute_localized_velocity_from_momentum(m=m_orig,weights=weights_orig,multi_gaussian_stds=multi_gaussian_stds,sz=sz,spacing=spacing)

    if publication_figures_directory is not None:
        plt.clf()
        plt.imshow(ring_im_orig[0, 0, ...], origin='lower')
        subsampled_quiver(localized_v_orig[0,1,...],localized_v_orig[0,0,...],color='red', scale=1, subsample=3)
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory,'{:s}_{:d}.pdf'.format('localized_v_orig', image_pair_nr)),bbox_inches='tight',pad_inches=0)

    phi0_orig,phi1_orig = compute_map_from_v(localized_v_orig,sz,spacing)

    if add_texture_to_image:
        ring_im = add_texture(ring_im_orig)
        if publication_figures_directory is not None:
            plt.clf()
            plt.imshow(ring_im[0, 0, ...],origin='lower')
            plt.axis('off')
            plt.savefig(os.path.join(publication_figures_directory, 'ring_im_orig_textured_{:d}.pdf'.format(image_pair_nr)),bbox_inches='tight',pad_inches=0)

    else:
        ring_im = ring_im_orig

    # deform image based on this map
    I0_source_orig = AdaptVal(Variable(torch.from_numpy(ring_im),requires_grad=False))
    I1_warped_orig = utils.compute_warped_image_multiNC(I0_source_orig, phi1_orig, spacing, spline_order=1)

    # define the label images
    I0_label_orig = AdaptVal(Variable(torch.from_numpy(ring_im_orig),requires_grad=False))
    I1_label_orig = utils.get_warped_label_map(I0_label_orig, phi1_orig, spacing )

    if publication_figures_directory is not None:
        plt.clf()
        plt.imshow(I1_label_orig[0, 0, ...].data.cpu().numpy(),origin='lower')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory, 'ring_im_warped_source_{:d}.pdf'.format(image_pair_nr)),bbox_inches='tight',pad_inches=0)

    if use_random_source:
        # the initially created target will become the source
        id_c_warped_t = utils.compute_warped_image_multiNC(AdaptVal(Variable(torch.from_numpy(id_c),requires_grad=False)), phi1_orig, spacing, spline_order=1)
        id_c_warped = id_c_warped_t.data.cpu().numpy()
        weights_warped_t = utils.compute_warped_image_multiNC(AdaptVal(Variable(torch.from_numpy(weights_orig),requires_grad=False)), phi1_orig, spacing, spline_order=1)
        weights_warped = weights_warped_t.data.cpu().numpy()

        warped_source_im_orig = I1_label_orig.data.cpu().numpy()

        m_warped_source = create_momentum(warped_source_im_orig, centered_map=id_c_warped, randomize_momentum_on_circle=randomize_momentum_on_circle,
                                          randomize_in_sectors=randomize_in_sectors,
                                          smooth_initial_momentum=smooth_initial_momentum,
                                          sz=sz, spacing=spacing,
                                          nr_of_angles=nr_of_angles,
                                          multiplier_factor=multiplier_factor,
                                          momentum_smoothing=momentum_smoothing,
                                          publication_figures_directory=publication_figures_directory,
                                          publication_prefix='random_source',
                                          image_pair_nr=image_pair_nr)

        localized_v_warped = compute_localized_velocity_from_momentum(m=m_warped_source, weights=weights_warped,
                                                                      multi_gaussian_stds=multi_gaussian_stds, sz=sz,
                                                                      spacing=spacing)

        if publication_figures_directory is not None:
            plt.clf()
            plt.imshow(warped_source_im_orig[0, 0, ...], origin='lower')
            subsampled_quiver(localized_v_warped[0, 1, ...], localized_v_warped[0, 0, ...], color='red', scale=1,subsample=3)
            plt.axis('image')
            plt.axis('off')
            plt.savefig(os.path.join(publication_figures_directory,'{:s}_{:d}.pdf'.format('random_source_localized_v', image_pair_nr)),bbox_inches='tight',pad_inches=0)

        phi0_w, phi1_w = compute_map_from_v(localized_v_warped, sz, spacing)

        if add_texture_to_image:
            warped_source_im = add_texture(warped_source_im_orig)
            if publication_figures_directory is not None:
                plt.clf()
                plt.imshow(ring_im[0, 0, ...],origin='lower')
                plt.axis('off')
                plt.savefig(os.path.join(publication_figures_directory, 'random_source_im_textured_{:d}.pdf'.format(image_pair_nr)),bbox_inches='tight',pad_inches=0)

        else:
            warped_source_im = warped_source_im_orig

        # deform these images based on the new map
        # deform image based on this map
        I0_source_w = AdaptVal(Variable(torch.from_numpy(warped_source_im), requires_grad=False))
        I1_warped_w = utils.compute_warped_image_multiNC(I0_source_w, phi1_w, spacing, spline_order=1)

        # define the label images
        I0_label_w = AdaptVal(Variable(torch.from_numpy(warped_source_im_orig), requires_grad=False))
        I1_label_w = utils.get_warped_label_map(I0_label_w, phi1_w, spacing)

    if use_random_source:
        I0_source = I0_source_w
        I1_warped = I1_warped_w
        I0_label = I0_label_w
        I1_label = I1_label_w
        m = m_warped_source
        phi0 = phi0_w
        phi1 = phi1_w
        weights = weights_warped
    else:
        I0_source = I0_source_orig
        I1_warped = I1_warped_orig
        I0_label = I0_label_orig
        I1_label = I1_label_orig
        m = m_orig
        phi0 = phi0_orig
        phi1 = phi1_orig
        weights = weights_orig

    std_im = compute_overall_std(weights,multi_gaussian_stds)

    if visualize_warped:
        plt.clf()
        # plot original image, warped image, and grids
        plt.subplot(3,4,1)
        plt.imshow(I0_source[0,0,...].data.cpu().numpy())
        plt.title('source')
        plt.subplot(3,4,2)
        plt.imshow(I1_warped[0,0,...].data.cpu().numpy())
        plt.title('warped = target')
        plt.subplot(3,4,3)
        plt.imshow(I0_source[0,0,...].data.cpu().numpy())
        plt.contour(phi0[0,0,...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.contour(phi0[0,1,...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.subplot(3,4,4)
        plt.imshow(I1_warped[0,0,...].data.cpu().numpy())
        plt.contour(phi1[0,0,...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.contour(phi1[0,1,...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')

        nr_of_weights = weights.shape[1]
        for cw in range(nr_of_weights):
            plt.subplot(3,4,5+cw)
            plt.imshow(weights[0, cw, ...], vmin=0.0, vmax=1.0)
            plt.title('w: std' + str(multi_gaussian_stds[cw]))
            plt.colorbar()

        plt.subplot(3,4,12)
        plt.imshow(std_im)
        plt.title('std')
        plt.colorbar()

        if print_warped_name is not None:
            plt.savefig(print_warped_name)
        else:
            plt.show()

    if publication_figures_directory is not None:
        plt.clf()
        plt.imshow(I0_source[0, 0, ...].data.cpu().numpy(),origin='lower')
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory, '{:s}_{:d}.pdf'.format('source_image', image_pair_nr)),bbox_inches='tight',pad_inches=0)

        plt.clf()
        plt.imshow(I1_warped[0, 0, ...].data.cpu().numpy(),origin='lower')
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory, '{:s}_{:d}.pdf'.format('target_image', image_pair_nr)),bbox_inches='tight',pad_inches=0)

        plt.clf()
        plt.imshow(I0_source[0, 0, ...].data.cpu().numpy(),origin='lower')
        plt.contour(phi0[0, 0, ...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.contour(phi0[0, 1, ...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory, '{:s}_{:d}.pdf'.format('source_image_with_grid', image_pair_nr)),bbox_inches='tight',pad_inches=0)

        plt.clf()
        plt.imshow(I1_warped[0, 0, ...].data.cpu().numpy(),origin='lower')
        plt.contour(phi1[0, 0, ...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.contour(phi1[0, 1, ...].data.cpu().numpy(), np.linspace(-1, 1, 40), colors='r', linestyles='solid')
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory,'{:s}_{:d}.pdf'.format('target_image_with_grid', image_pair_nr)), bbox_inches='tight',pad_inches=0)

        plt.clf()
        plt.imshow(std_im,origin='lower')
        plt.colorbar()
        plt.axis('image')
        plt.axis('off')
        plt.savefig(os.path.join(publication_figures_directory, '{:s}_{:d}.pdf'.format('std_im_source', image_pair_nr)),bbox_inches='tight',pad_inches=0)

    return I0_source.data.cpu().numpy(), I1_warped.data.cpu().numpy(), weights, \
           I0_label.data.cpu().numpy(), I1_label.data.cpu().numpy(), phi1.data.cpu().numpy(), m


def get_parameter_value(command_line_par,params, params_name, default_val, params_description):

    if command_line_par is None:
        ret = params[(params_name, default_val, params_description)]
    else:
        params[params_name]=command_line_par
        ret = command_line_par

    return ret

def get_parameter_value_flag(command_line_par,params, params_name, default_val, params_description):

    if command_line_par==default_val:
        ret = params[(params_name, default_val, params_description)]
    else:
        params[params_name]=command_line_par
        ret = command_line_par

    return ret

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Creates a synthetic registration results')

    parser.add_argument('--config', required=False, default=None, help='The main json configuration file that can be used to define the settings')

    parser.add_argument('--output_directory', required=False, default='synthetic_example_out', help='Where the output was stored (now this will be the input directory)')
    parser.add_argument('--nr_of_pairs_to_generate', required=False, default=10, type=int, help='number of image pairs to generate')
    parser.add_argument('--nr_of_circles_to_generate', required=False, default=None, type=int, help='number of circles to generate in an image') #2
    parser.add_argument('--circle_extent', required=False, default=None, type=float, help='Size of largest circle; image is [-0.5,0.5]^2') # 0.25

    parser.add_argument('--seed', required=False, type=int, default=None, help='Sets the random seed which affects data shuffling')

    parser.add_argument('--create_publication_figures', action='store_true', help='If set writes out figures illustrating the generation approach of first example')

    parser.add_argument('--use_random_source', action='store_true', help='if set then inital source is warped randomly, otherwise it is circular')

    parser.add_argument('--do_not_randomize_momentum', action='store_true', help='if set, momentum is deterministic')
    parser.add_argument('--do_not_randomize_in_sectors', action='store_true', help='if set and randomize momentum is on, momentum is only randomized uniformly over circles')
    parser.add_argument('--put_weights_between_circles', action='store_true', help='if set, the weights will change in-between circles, otherwise they will be colocated with the circles')
    parser.add_argument('--start_with_fluid_weight', action='store_true', help='if set then the innermost circle is not fluid, otherwise it is fluid')

    parser.add_argument('--weight_smoothing_std',required=False,default=0.02,type=float,help='Standard deviation to smooth the weights with; to assure sufficient regularity')
    parser.add_argument('--stds', required=False,type=str, default=None, help='standard deviations for the multi-Gaussian; default=[0.01,0.05,0.1,0.2]')
    parser.add_argument('--weights_not_fluid', required=False,type=str, default=None, help='weights for a non fluid circle; default=[0,0,0,1]')
    parser.add_argument('--weights_fluid', required=False,type=str, default=None, help='weights for a fluid circle; default=[0.2,0.5,0.2,0.1]')
    parser.add_argument('--weights_background', required=False,type=str, default=None, help='weights for the background; default=[0,0,0,1]')

    parser.add_argument('--nr_of_angles', required=False, default=None, type=int, help='number of angles for randomize in sector') #10
    parser.add_argument('--multiplier_factor', required=False, default=None, type=float, help='value the random momentum is multiplied by') #1.0
    parser.add_argument('--momentum_smoothing', required=False, default=None, type=int, help='how much the randomly generated momentum is smoothed') #0.05

    parser.add_argument('--sz', required=False, type=str, default=None, help='Desired size of synthetic example; default=[128,128]')

    args = parser.parse_args()

    if args.seed is not None:
        print('Setting the random seed to {:}'.format(args.seed))
        random.seed(args.seed)

    params = pars.ParameterDict()
    if args.config is not None:
        # load the configuration
        params.load_JSON(args.config)

    visualize = False
    visualize_warped = True
    print_images = True

    nr_of_pairs_to_generate = args.nr_of_pairs_to_generate

    nr_of_circles_to_generate = get_parameter_value(args.nr_of_circles_to_generate, params,'nr_of_circles_to_generate', 2, 'number of circles for the synthetic data')
    circle_extent = get_parameter_value(args.circle_extent, params, 'circle_extent', 0.02, 'Size of largest circle; image is [-0.5,0.5]^2')

    randomize_momentum_on_circle = get_parameter_value_flag(not args.do_not_randomize_momentum,params=params, params_name='randomize_momentum_on_circle',
                                                            default_val=True, params_description='randomizes the momentum on the circles')

    randomize_in_sectors = get_parameter_value_flag(not args.do_not_randomize_in_sectors, params=params, params_name='randomize_in_sectors',
                                               default_val=True, params_description='randomized the momentum sector by sector')

    put_weights_between_circles = get_parameter_value_flag(args.put_weights_between_circles, params=params, params_name='put_weights_between_circles',
                                                      default_val=False, params_description='if set, the weights will change in-between circles, otherwise they will be colocated with the circles')

    start_with_fluid_weight = get_parameter_value_flag(args.start_with_fluid_weight, params=params, params_name='start_with_fluid_weight',
                                                  default_val=False, params_description='if set then the innermost circle is not fluid, otherwise it is fluid')

    use_random_source = get_parameter_value_flag(args.use_random_source, params=params, params_name='use_random_source',
                                            default_val=False, params_description='if set then source image is already deformed (and no longer circular)')

    nr_of_angles = get_parameter_value(args.nr_of_angles,params,'nr_of_angles',10,'number of angles for randomize in sector')
    multiplier_factor = get_parameter_value(args.multiplier_factor,params,'multiplier_factor',0.5,'value the random momentum is multiplied by')
    momentum_smoothing = get_parameter_value(args.momentum_smoothing,params,'momentum_smoothing',0.05,'how much the randomly generated momentum is smoothed')

    if args.stds is None:
        multi_gaussian_stds_p = None
    else:
        mgsl = [float(item) for item in args.stds.split(',')]
        multi_gaussian_stds_p = list(np.array(mgsl))

    multi_gaussian_stds = get_parameter_value(multi_gaussian_stds_p, params, 'multi_gaussian_stds', list(np.array([0.01, 0.05, 0.1, 0.2])), 'multi gaussian standard deviations')
    multi_gaussian_stds = np.array(multi_gaussian_stds)

    if args.weights_not_fluid is None:
        weights_not_fluid_p = None
    else:
        cw = [float(item) for item in args.weights_not_fluid.split(',')]
        weights_not_fluid_p = list(np.array(cw))

    weights_not_fluid = get_parameter_value(weights_not_fluid_p, params, 'weights_not_fluid', list(np.array([0,0,0,1.0])), 'weights for the non-fluid regions')
    weights_not_fluid = np.array(weights_not_fluid)

    if len(weights_not_fluid)!=len(multi_gaussian_stds):
        raise ValueError('Need as many weights as there are standard deviations')


    if args.weights_fluid is None:
        weights_fluid_p = None
    else:
        cw = [float(item) for item in args.weights_fluid.split(',')]
        weights_fluid_p = list(np.array(cw))

    weights_fluid = get_parameter_value(weights_fluid_p, params, 'weights_fluid', list(np.array([0.2,0.5,0.2,0.1])), 'weights for fluid regions')
    weights_fluid = np.array(weights_fluid)

    if len(weights_fluid)!=len(multi_gaussian_stds):
        raise ValueError('Need as many weights as there are standard deviations')

    if args.weights_background is None:
        weights_neutral_p = None
    else:
        cw = [float(item) for item in args.weights_background.split(',')]
        weights_neutral_p = list(np.array(cw))

    weights_neutral = get_parameter_value(weights_neutral_p, params, 'weights_neutral', list(np.array([0,0,0,1.0])), 'weights in the neutral/background region')
    weights_neutral = np.array(weights_neutral)

    if len(weights_neutral)!=len(multi_gaussian_stds):
        raise ValueError('Need as many weights as there are standard deviations')

    if args.sz is None:
        sz_p = None
    else:
        cw = [int(item) for item in args.sz.split(',')]
        sz_p = np.array(cw)

    sz = get_parameter_value(sz_p, params, 'sz', [128,128], 'size of the synthetic example')
    if len(sz) != 2:
        raise ValueError('Only two dimensional synthetic examples are currently supported for sz parameter')

    sz = [1, 1, sz[0], sz[1]]
    spacing = 1.0 / (np.array(sz[2:]) - 1)

    output_dir = args.output_directory

    image_output_dir = os.path.join(output_dir,'brain_affine_icbm')
    label_output_dir = os.path.join(output_dir,'label_affine_icbm')
    misc_output_dir = os.path.join(output_dir,'misc')
    pdf_output_dir = os.path.join(output_dir,'pdf')
    publication_figs = os.path.join(output_dir,'publication_figs')

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    if not os.path.isdir(image_output_dir):
        os.makedirs(image_output_dir)

    if not os.path.isdir(label_output_dir):
        os.makedirs(label_output_dir)

    if not os.path.isdir(misc_output_dir):
        os.makedirs(misc_output_dir)

    if not os.path.isdir(pdf_output_dir):
        os.makedirs(pdf_output_dir)

    if args.create_publication_figures:
        if not os.path.isdir(publication_figs):
            os.makedirs(publication_figs)

    pt = dict()
    pt['source_images'] = []
    pt['target_images'] = []
    pt['source_ids'] = []
    pt['target_ids'] = []

    im_io = fio.ImageIO()
    # image hdr
    hdr = dict()
    hdr['space origin'] = np.array([0,0,0])
    hdr['spacing'] = np.array(list(spacing) + [spacing[-1]])
    hdr['space directions'] = np.array([['1', '0', '0'], ['0', '1', '0'], ['0', '0', '1']])
    hdr['dimension'] = 3
    hdr['space'] = 'left-posterior-superior'
    hdr['sizes'] = list(sz[2:])+[1]

    for n in range(nr_of_pairs_to_generate):

        print('Writing file pair ' + str(n+1) + '/' + str(nr_of_pairs_to_generate))

        if print_images:
            print_warped_name = os.path.join(pdf_output_dir,'registration_image_pair_{:05d}.pdf'.format(2*n+1))
        else:
            print_warped_name = None

        publication_figures_directory = None
        if args.create_publication_figures and (n==0):
            publication_figures_directory = publication_figs

        I0Source, I1Target, weights, I0Label, I1Label, gt_map, gt_m = \
            create_random_image_pair(weights_not_fluid=weights_not_fluid,
                                     weights_fluid=weights_fluid,
                                     weights_neutral=weights_neutral,
                                     weight_smoothing_std=args.weight_smoothing_std,
                                     multi_gaussian_stds=multi_gaussian_stds,
                                     randomize_momentum_on_circle=randomize_momentum_on_circle,
                                     randomize_in_sectors=randomize_in_sectors,
                                     put_weights_between_circles=put_weights_between_circles,
                                     start_with_fluid_weight=start_with_fluid_weight,
                                     use_random_source=use_random_source,
                                     nr_of_circles_to_generate=nr_of_circles_to_generate,
                                     circle_extent=circle_extent,
                                     sz=sz,spacing=spacing,
                                     nr_of_angles=nr_of_angles,
                                     multiplier_factor=multiplier_factor,
                                     momentum_smoothing=momentum_smoothing,
                                     visualize=visualize,
                                     visualize_warped=visualize_warped,
                                     print_warped_name=print_warped_name,
                                     publication_figures_directory=publication_figures_directory,
                                     image_pair_nr=n)

        source_filename = os.path.join(image_output_dir,'m{:d}.nii'.format(2*n+1))
        target_filename = os.path.join(image_output_dir,'m{:d}.nii'.format(2*n+1+1))
        source_label_filename = os.path.join(label_output_dir, 'm{:d}.nii'.format(2 * n + 1))
        target_label_filename = os.path.join(label_output_dir, 'm{:d}.nii'.format(2 * n + 1 + 1))

        gt_weights_filename = os.path.join(misc_output_dir,'gt_weights_{:05d}.pt'.format(2*n+1))
        gt_momentum_filename = os.path.join(misc_output_dir,'gt_momentum_{:05d}.pt'.format(2*n+1))
        gt_map_filename = os.path.join(misc_output_dir,'gt_map_{:05d}.pt'.format(2*n+1))

        reshape_size = list(sz[2:]) + [1]

        # save these files
        im_io.write(filename=source_filename,data=I0Source.view().reshape(reshape_size),hdr=hdr)
        im_io.write(filename=target_filename,data=I1Target.view().reshape(reshape_size),hdr=hdr)

        im_io.write(filename=source_label_filename, data=I0Label.view().reshape(reshape_size), hdr=hdr)
        im_io.write(filename=target_label_filename, data=I1Label.view().reshape(reshape_size), hdr=hdr)

        torch.save(weights,gt_weights_filename)
        torch.save(gt_map,gt_map_filename)
        torch.save(gt_m,gt_momentum_filename)

        # create source/target configuration
        pt['source_images'].append(source_filename)
        pt['target_images'].append(target_filename)
        pt['source_ids'].append(2*n+1)
        pt['target_ids'].append(2*n+1+1)

    filename_pt = os.path.join(output_dir,'used_image_pairs.pt')
    torch.save(pt,filename_pt)

    config_json = os.path.join(output_dir,'config.json')
    params.write_JSON(config_json)

