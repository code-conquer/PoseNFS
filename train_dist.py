import torch

import os
import numpy as np
import pprint

import yaml
from easydict import EasyDict as edict
import logging
import argparse
from timeit import default_timer as timer
import datetime

from src.build_your_net import bulid_up_network
from src.train_net import train
from src.dataloader import Dataloaders
from src.evaluate import evaluate
from src.search_methods import Search_Arch
from src.loss import MSELoss
from src.utils import   save_batch_image_with_joints,\
                    save_model,\
                    save_scripts_in_exp_dir,\
                    AverageMeter, \
                    load_ckpt,\
                    filter_arch_parameters, \
                    visualize_heatamp


from tensorboardX import SummaryWriter

import torch.distributed
import torch.nn.parallel
import torch.multiprocessing as mp
import torch.utils.data
import torch.utils.data.distributed
from torch.utils.data.distributed import DistributedSampler

def args():

    parser = argparse.ArgumentParser(description='Architecture Search')

    parser.add_argument('--cfg',            help='experiment configure file name',  required=True,   default='config.yaml', type=str)
    parser.add_argument('--exp_name',       help='experiment name',        default='NAS-0'     , type=str)
    parser.add_argument('--gpu',            help='gpu ids',                 default = '0,1',                      type =str)
    parser.add_argument('--load_ckpt',      help='reload the last save ckeckpoint in current directory', action='store_true', default=False)
    parser.add_argument('--debug',          help='save batch images ', action='store_true', default=False)
    parser.add_argument('--num_workers',    help='workers number (debug=0) ', default = 8,                      type =int)

    parser.add_argument('--param_flop',     help=' ', action='store_true', default=False)
    parser.add_argument('--show_arch_value',help='show_arch_value ', action='store_true', default=False)
    parser.add_argument('--search'    ,     help = 'search method: None,random,sync,second_order_gradient,first_order_gradient',type=str)
    parser.add_argument('--batchsize',      help='',   type =int)
    parser.add_argument('--visualize',     help=' ', action='store_true', default=False)

    parser.add_argument('--distributed', help="single node multi-gpus. \
                        see more in https://pytorch.org/tutorials/intermediate/ddp_tutorial.html",
                        action='store_true' ,default= False)
                        
    parser.add_argument('--local_rank', default=0, type=int,
                         help='node rank for distributed training')
    # parser.add_argument('--world-size', default=-1, type=int,
    #                 help='number of nodes for distributed training')
    # arser.add_argument('--rank', default=-1, type=int,
    #                     help='node rank for distributed training')
    # parser.add_argument('--dist-url', default='tcp://127.0.0.1:FREEPORT', type=str,
    #                     help='url used to set up distributed training')

    args = parser.parse_args()
    return args

def logging_set(output_dir,local_rank=None):
    if local_rank is not None:
        logging.basicConfig(filename = os.path.join(output_dir,'train_{}_rank{}.log'.format(datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S'),local_rank)),
                    format = '[#{}]%(message)s'.format(local_rank))
    else:
        logging.basicConfig(filename = os.path.join(output_dir,'train_{}.log'.format(datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))),
                    format = '%(message)s')
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    console = logging.StreamHandler()
    logging.getLogger().addHandler(console)
    return logger
    
def main():

    arg = args()
    
    if not os.path.exists(arg.exp_name):
        os.makedirs(arg.exp_name)

    assert arg.exp_name.split('/')[0]=='o',"'o' is the directory of experiment, --exp_name o/..."
    output_dir = arg.exp_name

    
    if arg.local_rank ==0:
        save_scripts_in_exp_dir(output_dir)

    
    logger = logging_set(output_dir,arg.local_rank)
    logger.info(arg)
    logger.info('\n================ experient name:[{}] ===================\n'.format(arg.exp_name))
    os.environ["CUDA_VISIBLE_DEVICES"] = arg.gpu

    torch.backends.cudnn.enabled = True
    torch.backends.cudnn.benchmark = True
    np.random.seed(0)
    torch.manual_seed(0)

    config = edict( yaml.load( open(arg.cfg,'r')))

    if arg.search:
        assert arg.search in ['None','sync','random','second_order_gradient','first_order_gradient']
        config.train.arch_search_strategy = arg.search

    if arg.batchsize:
        logger.info("update batchsize to {}".format(arg.batchsize) )
        config.train.batchsize = arg.batchsize

    config.num_workers = arg.num_workers
        
    print('GPU memory : \ntotal | used\n',os.popen(
        'nvidia-smi --query-gpu=memory.total,memory.used --format=csv,nounits,noheader'
            ).read())

    logger.info('------------------------------ configuration ---------------------------')
    logger.info('\n==> available {} GPUs , use numbers are {} device is {}\n'
                .format(torch.cuda.device_count(),os.environ["CUDA_VISIBLE_DEVICES"],torch.cuda.current_device()))
    # torch.cuda._initialized = True
    logger.info(pprint.pformat(config))
    logger.info('------------------------------- -------- ----------------------------')

    best = 0

    criterion = MSELoss()

    Arch = bulid_up_network(config,criterion)

    if  config.train.arch_search_strategy == 'random':

        logger.info("==>random seed is {}".format(config.train.random_seed))
        np.random.seed(config.train.random_seed)
        torch.manual_seed(config.train.random_seed)

        Arch.arch_parameters_random_search()

    if arg.param_flop:
        Arch._print_info()

    if len(arg.gpu)>1:
        use_multi_gpu = True
        
        if arg.distributed:
            torch.distributed.init_process_group(backend="nccl")
            #torch.distributed.init_process_group(backend="nccl",init_method='env://')
            local_rank = torch.distributed.get_rank()
            torch.cuda.set_device(local_rank)
            device = torch.device("cuda", local_rank)
            Arch.to(device)

            Arch = torch.nn.parallel.DistributedDataParallel(Arch,
                                                    device_ids=[local_rank],
                                                    output_device=local_rank,
                                                    find_unused_parameters=True)
            logger.info("local rank = {}".format(local_rank))
        else:
            Arch = torch.nn.DataParallel(Arch).cuda()
    else:
        use_multi_gpu = False
        Arch = Arch.cuda()
    
    Search = Search_Arch(Arch.module, config) if use_multi_gpu else Search_Arch(Arch, config)# Arch.module for nn.DataParallel

    search_strategy = config.train.arch_search_strategy

    if not arg.distributed:
        train_queue, arch_queue, valid_queue = Dataloaders(search_strategy,config,arg)
    else:
        train_queue, \
        arch_queue, \
        valid_queue, \
        train_sampler_dist, = Dataloaders(search_strategy,config,arg)
    #Note: if the search strategy is `None` or `SYNC`, the arch_queue is None!
        
    logger.info("\nNeural Architecture Search strategy is {}".format(search_strategy))
    assert search_strategy in ['first_order_gradient','random','None','second_order_gradient','sync']

    if  search_strategy == 'sync':
        # arch_parameters is also registered to model's parameters
        # so the weight-optimizer will also update the arch_parameters
        logger.info("sync: The arch_parameters is also optimized by weight-optmizer synchronously")
        optimizer = torch.optim.Adam(Arch.parameters(),  lr = config.train.w_lr_cosine_begin ,)

    else:
        # if search strategy is None,random,second_order_gradient and so on
        # the arch_parameters will be filtered by the weight-optimizer
        optimizer = torch.optim.Adam(filter_arch_parameters(Arch),  lr = config.train.w_lr_cosine_begin ,)
    #scheduler = torch.optim.lr_scheduler.StepLR(optimizer,  step_size = config.train.lr_step_size,
     #                                                       gamma = config.train.lr_decay_gamma )
    if config.train.scheduler_name == "MultiStepLR":
        scheduler =torch.optim.lr_scheduler.MultiStepLR(optimizer, config.train.LR_STEP, config.train.LR_FACTOR)
    elif config.train.scheduler_name == "CosineAnnealingLR":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                        T_max = config.train.epoch_end,
                                                        eta_min = config.train.w_lr_cosine_end)

    # best_result
    
    
    logger.info("\n=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+= training +=+=+=+=+=+=+=+=+=+=+=+=+=+=+=+==")
    begin, end = config.train.epoch_begin, config.train.epoch_end

    if arg.load_ckpt:
        if use_multi_gpu:
            begin ,best = load_ckpt(Arch.module, optimizer, scheduler, output_dir,logger)
        else:
            begin ,best = load_ckpt(Arch,optimizer, scheduler, output_dir, logger)

    for epoch in range(begin, end):
       
        lr = scheduler.get_lr()[0]
        logger.info('==>time:({})--training...... current learning rate is {:.7f}'.format(datetime.datetime.now(),lr))

        if arg.distributed:
            train_sampler_dist.set_epoch(epoch)
            #valid_sampler_dist.set_epoch(epoch)
        
        train(epoch, train_queue, arch_queue ,Arch ,Search,criterion, optimizer,lr ,search_strategy ,output_dir,logger,config, arg,)
        scheduler.step()

        if not arg.distributed or (arg.distributed and arg.local_rank==0):

            eval_results = evaluate( Arch, valid_queue , config, output_dir)

            if use_multi_gpu :
                best = save_model(epoch, best, eval_results, Arch.module, optimizer, scheduler, output_dir, logger)
            else:
                best = save_model(epoch, best, eval_results, Arch, optimizer, scheduler, output_dir, logger)
            



if __name__ == '__main__':
    main()
