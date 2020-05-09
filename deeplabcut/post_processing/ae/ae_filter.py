import numpy as np
import data_input
from layered_ae import VAE


def filter(cfg,points,p,p_bound,num_epoch=1000):
  data_obj = data_input.Data(points,p,p_bound)

  train_data_noisy, train_data_inter, train_data_denoised, npfactor = data_obj.get_training_data()

  network_arch = dict(encode1 = 64,
                      encode2 = 128,
                      encode3 = 256,
                      decode0 = 256,
                      decode1 = 128,
                      decode2 = 64,
                      latent_s = 20,
                      input_size = len(train_data_noisy[0]),
                      output_size = len(train_data_denoised[0]))
  batch_s = min(512,len(train_data_noisy))

  with open("./training_output/training", "w") as f:
    vae = VAE(network_arch, batch_s, num_epoch, f, "./training_output/model", model_summary="training_output/model")
    vae.train(train_data_noisy,train_data_inter,train_data_denoised,print_iter=5)
    noisy_data,_=data_obj.get_all_original_data()
    denoised_data = vae.reconstruct(noisy_data)
    return_data = data_obj.reconstruct_original_data(denoised_data)

  mean_x = return_data[:,[2*i for i in range(int(len(return_data[0])/2))]]
  mean_y = return_data[:,[2*i+1 for i in range(int(len(return_data[0])/2))]]
  return mean_x,mean_y
