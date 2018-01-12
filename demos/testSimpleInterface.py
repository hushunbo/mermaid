import set_pyreg_paths

import numpy as np

import pyreg.simple_interface as SI
import pyreg.example_generation as EG
import pyreg.module_parameters as pars

# keep track of general parameters
params = pars.ParameterDict()

len = 64
dim = 2
szEx = np.tile( len, dim )         # size of the desired images: (sz)^dim
I0,I1,spacing= EG.CreateSquares(dim).create_image_pair(szEx,params) # create a default image size with two sample squares
#I0,I1,spacing = eg.CreateRealExampleImages(dim).create_image_pair() # create a default image size with two sample squares

"""
Known registration models are:
------------------------------
                     total_variation_map: displacement-based total variation registration
                 svf_vector_momentum_map: map-based stationary velocity field using the vector momentum
               svf_vector_momentum_image: image-based stationary velocity field using the vector momentum
                              affine_map: map-based affine registration
                 svf_scalar_momentum_map: map-based stationary velocity field using the scalar momentum
                           curvature_map: displacement-based curvature registration
                    lddmm_shooting_image: image-based shooting-based LDDMM using the vector momentum
                           diffusion_map: displacement-based diffusion registration
                               svf_image: image-based stationary velocity field
                                 svf_map: map-based stationary velocity field
               svf_scalar_momentum_image: image-based stationary velocity field using the scalar momentum
                svf_quasi_momentum_image: EXPERIMENTAL: Image-based SVF version which estimates velcocity based on a smoothed vetor field
    lddmm_shooting_scalar_momentum_image: image-based shooting-based LDDMM using the scalar momentum
      lddmm_shooting_scalar_momentum_map: map-based shooting-based LDDMM using the scalar momentum
                      lddmm_shooting_map: map-based shooting-based LDDMM using the vector momentum
"""

# print possible model names
SI.RegisterImagePair().print_available_models()
all_models = SI.RegisterImagePair().get_available_models()

try_all_models = False

if try_all_models:
    # try all the models
    for model_name in all_models:
        print('Registering with model: ' + model_name )
        SI.RegisterImagePair().register_images(I0, I1, spacing, model_name=model_name)
else:
    # just try one of them, explicitly specified
    #SI.RegisterImagePair().register_images(I0, I1, spacing, model_name='lddmm_shooting_scalar_momentum_map')
    SI.RegisterImagePair().register_images(I0, I1, spacing, model_name='diffusion_map')




