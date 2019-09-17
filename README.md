# Introduction

This repository is our PyTorch implementation of the paper [Pose Neural Fabrics Search (PNFS)](https://arxiv.org/pdf/1909.07068.pdf) (*[arXiv 1909.07068](https://arxiv.org/abs/1909.07068)*).   

# Installation

## Dependenices
```
torch (version >=1.0.0)
torchvision
opencv-python
pycocotools
scipy
scikit-image
pyyaml
easydict
```

## Data preparation
We follow the steps of [this repository](https://github.com/microsoft/human-pose-estimation.pytorch) for preparing `MPII` and `COCO` dataset, please see the [https://github.com/microsoft/human-pose-estimation.pytorch#data-preparation](https://github.com/microsoft/human-pose-estimation.pytorch#data-preparation).

# Usage

## Create the `o` directory to reserve each experiment's output
```
mkdir o  
```
## Train the model
```
python train.py \
--cfg configs/our3.yaml \
--exp_name o/your_train_experiment_name \
--gpu 0,1 
```
other optional commands for training

```
--batchsize 32  
--param_flop   // report parameters and FLOPs
--search search_method_name   // options: ['None','random','sync','first_order_gradient','second_order_gradient']
--debug   // visualize the input data
--visualize // visualize the predicted heatmaps for an image (per 5 epcohes in training)
--show_arch_value   // print the parameters of architecture in the training process
```
#### Distributed multi-gpu training in a single machine (node)

```
sh distributed.sh
```
`nproc_per_node` means how many gpus are used.
## Test the model
```
python test.py \
--cfg configs/ours3.yaml \
--exp_name o/your_test_experiment_name \
--gpu 0,1 \
--test_model o/path_to_your_saved_model \
--flip_test 
```
other optional commands for testing
```
--visualize   // visualize the predicted heatmaps
--param_flop
---margin 1.15  // [1.0,1.5] margin between bbox border and input size when testing 
--flip_test   // horizontal flip test
--use_dt   // use the detection results of COCO val set or test-dev set
```

## Detailed Settings

All detailed settings of the model is recorded in the [`configs/*.yaml`](configs/).

#### Configuration for Fabric-Subnetwork

A snippet of the `*.yaml` for the hyperparameters of subnetworks :
```yaml
subnetwork_config:

  dataset_name: 'coco'
  parts_num : 3
  cell_config:
  
      vector_in_pixel : True
      vector_dim: 8
      convolution_mode: '2D'
      
      search_alpha: true
      search_beta: true
      operators: ["skip_connect", "Sep_Conv_3x3","Atr_Conv_3x3","max_pool_3x3"] # 

      depth: 7
      cut_layers_num: 4  # first several layers
      size_types: [4,8,16,32] # scales is [1/4, 1/8, 1/16, 1/32]
      hidden_states_num: 1
      factor: 16
      input_nodes_num: 1 # default
```



#### Body Parts Mode
The body keypoints assignment for different parts is defined in [`src/network_factory/body_parts.py`](src/network_factory/body_parts.py)

#### Vector Representation

We provide two types of convolutional mode `Conv2d` and `Conv3d` in [`src/network_factory/subnetwork.py`](src/network_factory/subnetwork.py) to construct the vector representation (`5D-Tensor`) of keypoint. We use the `Conv2d` mode (reshape `5D-Tensor` to `4D-Tensor`) by default.

#### Exploration

- More potential cutomized computing units can be defined as candidate operations in [`src/architecture/operators.py`](src/architecture/operators.py).

### Citation

If you use this code in your research, please consider citing:

```
@inproceedings{yang2019pnfs,
  title={Pose Neural Fabrics Search},
  author={Yang, Sen and Yang, Wankou and Cui, Zhen},
  journal={arXiv preprint arXiv:1909.07068},
  year={2019}
}
```

