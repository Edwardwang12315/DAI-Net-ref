# -*- coding:utf-8 -*-

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function

import os

import torch
import torch.nn as nn
import torch.nn.init as init
import torch.nn.functional as F
from torch.autograd import Variable, Function

from layers import *
from data.config import cfg

import numpy as np
import matplotlib.pyplot as plt


class Interpolate(nn.Module):
    # 插值的方法对张量进行上采样或下采样
    def __init__(self, scale_factor):
        super(Interpolate, self).__init__()
        self.scale_factor = scale_factor

    def forward(self, x):
        x = nn.functional.interpolate(x, scale_factor=self.scale_factor, mode='nearest')
        return x


class FEM(nn.Module):
    """docstring for FEM"""

    def __init__(self, in_planes):
        super(FEM, self).__init__()
        inter_planes = in_planes // 3
        inter_planes1 = in_planes - 2 * inter_planes
        self.branch1 = nn.Conv2d(
            in_planes, inter_planes, kernel_size=3, stride=1, padding=3, dilation=3)

        self.branch2 = nn.Sequential(
            nn.Conv2d(in_planes, inter_planes, kernel_size=3,
                      stride=1, padding=3, dilation=3),
            nn.ReLU(inplace=True),
            nn.Conv2d(inter_planes, inter_planes, kernel_size=3,
                      stride=1, padding=3, dilation=3)
        )
        self.branch3 = nn.Sequential(
            nn.Conv2d(in_planes, inter_planes1, kernel_size=3,
                      stride=1, padding=3, dilation=3),
            nn.ReLU(inplace=True),
            nn.Conv2d(inter_planes1, inter_planes1, kernel_size=3,
                      stride=1, padding=3, dilation=3),
            nn.ReLU(inplace=True),
            nn.Conv2d(inter_planes1, inter_planes1, kernel_size=3,
                      stride=1, padding=3, dilation=3)
        )

    def forward(self, x):
        x1 = self.branch1(x)
        x2 = self.branch2(x)
        x3 = self.branch3(x)
        out = torch.cat((x1, x2, x3), dim=1)
        out = F.relu(out, inplace=True)
        return out


class DSFD(nn.Module):
    """Single Shot Multibox Architecture
    The network is composed of a base VGG network followed by the
    added multibox conv layers.  Each multibox layer branches into
        1) conv2d for class conf scores
        2) conv2d for localization predictions
        3) associated priorbox layer to produce default bounding
           boxes specific to the layer's feature map size.
    See: https://arxiv.org/pdf/1512.02325.pdf for more details.

    Args:
        phase: (string) Can be "test" or "train"
        size: input image size
        base: VGG16 layers for input, size of either 300 or 500
        extras: extra layers that feed to multibox loc and conf layers
        head: "multibox head" consists of loc and conf conv layers
    """

    def __init__(self, phase, base, extras, fem, head1, head2, num_classes):
        super(DSFD, self).__init__()
        '''
        
        '''
        self.phase = phase
        self.num_classes = num_classes
        self.vgg = nn.ModuleList(base)
        if False:
            self.L2Normof1 = L2Norm(256, 10)
            self.L2Normof2 = L2Norm(512, 8)
            self.L2Normof3 = L2Norm(512, 5)
    
            self.extras = nn.ModuleList(extras)
            self.fpn_topdown = nn.ModuleList(fem[0])
            self.fpn_latlayer = nn.ModuleList(fem[1])
    
            self.fpn_fem = nn.ModuleList(fem[2])
    
            self.L2Normef1 = L2Norm(256, 10)
            self.L2Normef2 = L2Norm(512, 8)
            self.L2Normef3 = L2Norm(512, 5)
    
            self.loc_pal1 = nn.ModuleList(head1[0])#nn.ModuleList是一种存储子模块的工具
            self.conf_pal1 = nn.ModuleList(head1[1])
    
            self.loc_pal2 = nn.ModuleList(head2[0])
            self.conf_pal2 = nn.ModuleList(head2[1])

        # the reflectance decoding branch
        # 反射图解码模块
        self.ref = nn.Sequential(
            nn.Conv2d(64, 64, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            Interpolate(2),#上采样
            nn.Conv2d(64, 3, kernel_size=3, padding=1),
            nn.Sigmoid()
        )

        # 计算teacher模型和学生模型的KL散度
        self.KL = DistillKL(T=4.0)

        if self.phase == 'test':
            self.softmax = nn.Softmax(dim=-1)
            self.detect = Detect(cfg)

    def _upsample_prod(self, x, y):
        _, _, H, W = y.size()
        return F.upsample(x, size=(H, W), mode='bilinear') * y
    # 反射图解码通路
    def enh_forward(self, x):

        x = x[:1]
        for k in range(5):
            x = self.vgg[k](x)

        R = self.ref(x)

        return R

    def test_forward(self, x):
        size = x.size()[2:]
        pal1_sources = list()
        pal2_sources = list()
        loc_pal1 = list()
        conf_pal1 = list()
        loc_pal2 = list()
        conf_pal2 = list()
        
        for k in range( 5 ) :  # 检测时为 16
            x = self.vgg[k](x)
            if k == 4:
                x_ = x
        R = self.ref(x_[0:1])
        
        # print( '暗图' )
        # image = np.transpose( R[ 0 ].detach().cpu().numpy() , (1 , 2 , 0) )  # 调整维度顺序 [C, H, W] → [H, W, C]
        # image = (image * 255).astype( np.uint8 )
        # plt.imshow( image )
        # plt.axis( 'off' )
        # # 保存图像到文件
        # plt.savefig( f'test_暗图.png' , bbox_inches = 'tight' , pad_inches = 0 , dpi = 800 )
        # exit()
        
        if False:
            of1 = x
            s = self.L2Normof1(of1)
            pal1_sources.append(s)
            # apply vgg up to fc7
            for k in range(16, 23):
                x = self.vgg[k](x)
            of2 = x
            s = self.L2Normof2(of2)
            pal1_sources.append(s)
    
            for k in range(23, 30):
                x = self.vgg[k](x)
            of3 = x
            s = self.L2Normof3(of3)
            pal1_sources.append(s)
    
            for k in range(30, len(self.vgg)):
                x = self.vgg[k](x)
            of4 = x
            pal1_sources.append(of4)
            # apply extra layers and cache source layer outputs
    
            for k in range(2):
                x = F.relu(self.extras[k](x), inplace=True)
            of5 = x
            pal1_sources.append(of5)
            for k in range(2, 4):
                x = F.relu(self.extras[k](x), inplace=True)
            of6 = x
            pal1_sources.append(of6)
    
            conv7 = F.relu(self.fpn_topdown[0](of6), inplace=True)
    
            x = F.relu(self.fpn_topdown[1](conv7), inplace=True)
            conv6 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[0](of5)), inplace=True)
    
            x = F.relu(self.fpn_topdown[2](conv6), inplace=True)
            convfc7_2 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[1](of4)), inplace=True)
    
            x = F.relu(self.fpn_topdown[3](convfc7_2), inplace=True)
            conv5 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[2](of3)), inplace=True)
    
            x = F.relu(self.fpn_topdown[4](conv5), inplace=True)
            conv4 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[3](of2)), inplace=True)
    
            x = F.relu(self.fpn_topdown[5](conv4), inplace=True)
            conv3 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[4](of1)), inplace=True)
    
            ef1 = self.fpn_fem[0](conv3)
            ef1 = self.L2Normef1(ef1)
            ef2 = self.fpn_fem[1](conv4)
            ef2 = self.L2Normef2(ef2)
            ef3 = self.fpn_fem[2](conv5)
            ef3 = self.L2Normef3(ef3)
            ef4 = self.fpn_fem[3](convfc7_2)
            ef5 = self.fpn_fem[4](conv6)
            ef6 = self.fpn_fem[5](conv7)
    
            pal2_sources = (ef1, ef2, ef3, ef4, ef5, ef6)
            for (x, l, c) in zip(pal1_sources, self.loc_pal1, self.conf_pal1):
                loc_pal1.append(l(x).permute(0, 2, 3, 1).contiguous())
                conf_pal1.append(c(x).permute(0, 2, 3, 1).contiguous())
    
            for (x, l, c) in zip(pal2_sources, self.loc_pal2, self.conf_pal2):
                loc_pal2.append(l(x).permute(0, 2, 3, 1).contiguous())
                conf_pal2.append(c(x).permute(0, 2, 3, 1).contiguous())
    
            features_maps = []
            for i in range(len(loc_pal1)):
                feat = []
                feat += [loc_pal1[i].size(1), loc_pal1[i].size(2)]
                features_maps += [feat]
    
            loc_pal1 = torch.cat([o.view(o.size(0), -1)
                                  for o in loc_pal1], 1)
            conf_pal1 = torch.cat([o.view(o.size(0), -1)
                                   for o in conf_pal1], 1)
    
            loc_pal2 = torch.cat([o.view(o.size(0), -1)
                                  for o in loc_pal2], 1)
            conf_pal2 = torch.cat([o.view(o.size(0), -1)
                                   for o in conf_pal2], 1)
    
            priorbox = PriorBox(size, features_maps, cfg, pal=1)
            self.priors_pal1 = Variable(priorbox.forward(), volatile=True)
    
            priorbox = PriorBox(size, features_maps, cfg, pal=2)
            self.priors_pal2 = Variable(priorbox.forward(), volatile=True)
    
            if self.phase == 'test':
                output = self.detect.forward(
                    loc_pal2.view(loc_pal2.size(0), -1, 4),
                    self.softmax(conf_pal2.view(conf_pal2.size(0), -1,
                                                self.num_classes)),  # conf preds
                    self.priors_pal2.type(type(x.data))
                )
    
            else:
                output = (
                    loc_pal1.view(loc_pal1.size(0), -1, 4),
                    conf_pal1.view(conf_pal1.size(0), -1, self.num_classes),
                    self.priors_pal1,
                    loc_pal2.view(loc_pal2.size(0), -1, 4),
                    conf_pal2.view(conf_pal2.size(0), -1, self.num_classes),
                    self.priors_pal2)
        # return output, R
        return R

    # during training, the model takes the paired images, and their pseudo GT illumination maps from the Retinex Decom Net
    def forward(self, x, x_light, I, I_light):
        size = x.size()[2:]
        pal1_sources = list()
        pal2_sources = list()
        loc_pal1 = list()
        conf_pal1 = list()
        loc_pal2 = list()
        conf_pal2 = list()

        # 检测主线和Retinex主线分离
        # apply vgg up to conv4_3 relu
        # x输入暗图 xlight输入亮图
        for k in range(5):
            x_light = self.vgg[k](x_light)

        for k in range(5): # 检测时为 16
            x = self.vgg[k](x)
            # x检测通路的输入
            if k == 4:
                x_dark = x
                # xlight、xdark分解通路的输入

        # extract the shallow features and forward them into the reflectance branch:
        # R_dark、R_light是对应的反射图
        R_dark = self.ref(x_dark)
        R_light = self.ref(x_light)
        
        # print( '暗图' )
        # image = np.transpose( R_dark[ 0 ].detach().cpu().numpy() , (1 , 2 , 0) )  # 调整维度顺序 [C, H, W] → [H, W, C]
        # image = (image * 255).astype( np.uint8 )
        # plt.imshow( image )
        # plt.axis( 'off' )
        # # 保存图像到文件
        # plt.savefig( f'train_暗图.png' , bbox_inches = 'tight' , pad_inches = 0 , dpi = 800 )
		#
        # print( '亮图' )
        # image = np.transpose( R_light[ 0 ].detach().cpu().numpy() , (1 , 2 , 0) )  # 调整维度顺序 [C, H, W] → [H, W, C]
        # image = (image * 255).astype( np.uint8 )
        # plt.imshow( image )
        # plt.axis( 'off' )
        # # 保存图像到文件
        # plt.savefig( f'train_亮图.png' , bbox_inches = 'tight' , pad_inches = 0 , dpi = 800 )
        
        # Interchange
        # I是Retinex Net生成的低光照下的光照图
        x_dark_2 = (I * R_light).detach()
        x_light_2 = (I_light * R_dark).detach()

        for k in range(5):
            x_light_2 = self.vgg[k](x_light_2)
        for k in range(5):
            x_dark_2 = self.vgg[k](x_dark_2)

        # Redecomposition
        # 重新分解
        R_dark_2 = self.ref(x_light_2)
        R_light_2 = self.ref(x_dark_2)

        # mutual feature alignment loss
        x_light = x_light.flatten(start_dim=2).mean(dim=-1)
        x_dark = x_dark.flatten(start_dim=2).mean(dim=-1)
        x_light_2 = x_light_2.flatten(start_dim=2).mean(dim=-1)
        x_dark_2 = x_dark_2.flatten(start_dim=2).mean(dim=-1)
        # 经过网络提取特征后的KL散度损失
        loss_mutual = cfg.WEIGHT.MC * (self.KL(x_light, x_dark) + self.KL(x_dark, x_light) + \
                             self.KL(x_light_2, x_dark_2) + self.KL(x_dark_2, x_light_2))

        if False:
            # the following is the rest of the original detection pipeline
            of1 = x
            s = self.L2Normof1(of1)
            pal1_sources.append(s)
            # apply vgg up to fc7
            for k in range(16, 23):
                x = self.vgg[k](x)
            of2 = x
            s = self.L2Normof2(of2)
            pal1_sources.append(s)
    
            for k in range(23, 30):
                x = self.vgg[k](x)
            of3 = x
            s = self.L2Normof3(of3)
            pal1_sources.append(s)
    
            for k in range(30, len(self.vgg)):
                x = self.vgg[k](x)
            of4 = x
            pal1_sources.append(of4)
            # apply extra layers and cache source layer outputs
    
            for k in range(2):
                x = F.relu(self.extras[k](x), inplace=True)
            of5 = x
            pal1_sources.append(of5)
            for k in range(2, 4):
                x = F.relu(self.extras[k](x), inplace=True)
            of6 = x
            pal1_sources.append(of6)
    
            conv7 = F.relu(self.fpn_topdown[0](of6), inplace=True)
    
            x = F.relu(self.fpn_topdown[1](conv7), inplace=True)
            conv6 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[0](of5)), inplace=True)
    
            x = F.relu(self.fpn_topdown[2](conv6), inplace=True)
            convfc7_2 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[1](of4)), inplace=True)
    
            x = F.relu(self.fpn_topdown[3](convfc7_2), inplace=True)
            conv5 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[2](of3)), inplace=True)
    
            x = F.relu(self.fpn_topdown[4](conv5), inplace=True)
            conv4 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[3](of2)), inplace=True)
    
            x = F.relu(self.fpn_topdown[5](conv4), inplace=True)
            conv3 = F.relu(self._upsample_prod(
                x, self.fpn_latlayer[4](of1)), inplace=True)
    
            ef1 = self.fpn_fem[0](conv3)
            ef1 = self.L2Normef1(ef1)
            ef2 = self.fpn_fem[1](conv4)
            ef2 = self.L2Normef2(ef2)
            ef3 = self.fpn_fem[2](conv5)
            ef3 = self.L2Normef3(ef3)
            ef4 = self.fpn_fem[3](convfc7_2)
            ef5 = self.fpn_fem[4](conv6)
            ef6 = self.fpn_fem[5](conv7)
    
            pal2_sources = (ef1, ef2, ef3, ef4, ef5, ef6)
            for (x, l, c) in zip(pal1_sources, self.loc_pal1, self.conf_pal1):
                loc_pal1.append(l(x).permute(0, 2, 3, 1).contiguous())
                conf_pal1.append(c(x).permute(0, 2, 3, 1).contiguous())
    
            for (x, l, c) in zip(pal2_sources, self.loc_pal2, self.conf_pal2):
                loc_pal2.append(l(x).permute(0, 2, 3, 1).contiguous())
                conf_pal2.append(c(x).permute(0, 2, 3, 1).contiguous())
    
            features_maps = []
            for i in range(len(loc_pal1)):
                feat = []
                feat += [loc_pal1[i].size(1), loc_pal1[i].size(2)]
                features_maps += [feat]
    
            loc_pal1 = torch.cat([o.view(o.size(0), -1)
                                  for o in loc_pal1], 1)
            conf_pal1 = torch.cat([o.view(o.size(0), -1)
                                   for o in conf_pal1], 1)
    
            loc_pal2 = torch.cat([o.view(o.size(0), -1)
                                  for o in loc_pal2], 1)
            conf_pal2 = torch.cat([o.view(o.size(0), -1)
                                   for o in conf_pal2], 1)
    
            priorbox = PriorBox(size, features_maps, cfg, pal=1)
            self.priors_pal1 = Variable(priorbox.forward(), volatile=True)
    
            priorbox = PriorBox(size, features_maps, cfg, pal=2)
            self.priors_pal2 = Variable(priorbox.forward(), volatile=True)
    
            if self.phase == 'test':
                output = self.detect.forward(
                    loc_pal2.view(loc_pal2.size(0), -1, 4),
                    self.softmax(conf_pal2.view(conf_pal2.size(0), -1,
                                                self.num_classes)),  # conf preds
                    self.priors_pal2.type(type(x.data))
                )
    
            else:
                output = (
                    loc_pal1.view(loc_pal1.size(0), -1, 4),
                    conf_pal1.view(conf_pal1.size(0), -1, self.num_classes),
                    self.priors_pal1,
                    loc_pal2.view(loc_pal2.size(0), -1, 4),
                    conf_pal2.view(conf_pal2.size(0), -1, self.num_classes),
                    self.priors_pal2)

        # packing the outputs from the reflectance decoder:
        # return output, [R_dark, R_light, R_dark_2, R_light_2], loss_mutual
        return [ R_dark , R_light , R_dark_2 , R_light_2 ] , loss_mutual

    def load_weights(self, base_file):
        other, ext = os.path.splitext(base_file)
        if ext == '.pkl' or '.pth':
            print('Loading weights into state dict...')
            mdata = torch.load(base_file,
                               map_location=lambda storage, loc: storage)

            epoch = 0
            self.load_state_dict(mdata)
            print('Finished!')
        else:
            print('Sorry only .pth and .pkl files supported.')
        return epoch

    def xavier(self, param):
        init.xavier_uniform(param)

    def weights_init(self, m):
        if isinstance(m, nn.Conv2d):
            self.xavier(m.weight.data)
            m.bias.data.zero_()

        if isinstance(m, nn.ConvTranspose2d):
            self.xavier(m.weight.data)
            if 'bias' in m.state_dict().keys():
                m.bias.data.zero_()

        if isinstance(m, nn.BatchNorm2d):
            m.weight.data[...] = 1
            m.bias.data.zero_()


vgg_cfg = [64, 64, 'M',
           #128, 128, 'M', 256, 256, 256, 'C', 512, 512, 512, 'M', 512, 512, 512, 'M'
        ]

extras_cfg = [256, 'S', 512, 128, 'S', 256]

fem_cfg = [256, 512, 512, 1024, 512, 256]


def fem_module(cfg):
    topdown_layers = []
    lat_layers = []
    fem_layers = []

    topdown_layers += [nn.Conv2d(cfg[-1], cfg[-1],
                                 kernel_size=1, stride=1, padding=0)]
    for k, v in enumerate(cfg):
        fem_layers += [FEM(v)]
        cur_channel = cfg[len(cfg) - 1 - k]
        if len(cfg) - 1 - k > 0:
            last_channel = cfg[len(cfg) - 2 - k]
            topdown_layers += [nn.Conv2d(cur_channel, last_channel,
                                         kernel_size=1, stride=1, padding=0)]
            lat_layers += [nn.Conv2d(last_channel, last_channel,
                                     kernel_size=1, stride=1, padding=0)]
    return (topdown_layers, lat_layers, fem_layers)


def vgg(cfg, i, batch_norm=False):
    layers = []
    in_channels = i
    for v in cfg:
        if v == 'M':
            layers += [nn.MaxPool2d(kernel_size=2, stride=2)]
        elif v == 'C':
            layers += [nn.MaxPool2d(kernel_size=2, stride=2, ceil_mode=True)]
        else:
            conv2d = nn.Conv2d(in_channels, v, kernel_size=3, padding=1)
            if batch_norm:
                layers += [conv2d, nn.BatchNorm2d(v), nn.ReLU(inplace=True)]
            else:
                layers += [conv2d, nn.ReLU(inplace=True)]
            in_channels = v
    if False:
        conv6 = nn.Conv2d(512, 1024, kernel_size=3, padding=3, dilation=3)
        conv7 = nn.Conv2d(1024, 1024, kernel_size=1)
        layers += [conv6,
                   nn.ReLU(inplace=True), conv7, nn.ReLU(inplace=True)]
    return layers


def add_extras(cfg, i, batch_norm=False):
    # Extra layers added to VGG for feature scaling
    layers = []
    in_channels = i
    flag = False
    for k, v in enumerate(cfg):
        if in_channels != 'S':
            if v == 'S':
                layers += [nn.Conv2d(in_channels, cfg[k + 1],
                                     kernel_size=(1, 3)[flag], stride=2, padding=1)]
            else:
                layers += [nn.Conv2d(in_channels, v, kernel_size=(1, 3)[flag])]
            flag = not flag
        in_channels = v
    return layers


def multibox(vgg, extra_layers, num_classes):
    loc_layers = []
    conf_layers = []
    vgg_source = [14, 21, 28, -2]

    for k, v in enumerate(vgg_source):
        loc_layers += [nn.Conv2d(vgg[v].out_channels,
                                 4, kernel_size=3, padding=1)]
        conf_layers += [nn.Conv2d(vgg[v].out_channels,
                                  num_classes, kernel_size=3, padding=1)]
    for k, v in enumerate(extra_layers[1::2], 2):
        loc_layers += [nn.Conv2d(v.out_channels,
                                 4, kernel_size=3, padding=1)]
        conf_layers += [nn.Conv2d(v.out_channels,
                                  num_classes, kernel_size=3, padding=1)]
    return (loc_layers, conf_layers)


def build_net_dark(phase, num_classes=2):
    base = vgg(vgg_cfg, 3)
    # extras = add_extras(extras_cfg, 1024)
    # head1 = multibox(base, extras, num_classes)
    # head2 = multibox(base, extras, num_classes)
    # fem = fem_module(fem_cfg)
    
    extras =None
    head1 = None
    head2 = None
    fem = None
    return DSFD(phase, base, extras, fem, head1, head2, num_classes)


class DistillKL(nn.Module):
    """KL divergence for distillation"""
    # 知识蒸馏模块，处理KL散度
    def __init__(self, T):
        super(DistillKL, self).__init__()
        self.T = T

    def forward(self, y_s, y_t):
        # y_s学生模型的输出，y_t 教师模型的输出
        p_s = F.log_softmax(y_s / self.T, dim=1)#对数概率分布
        p_t = F.softmax(y_t / self.T, dim=1)#概率分布
        # 计算KL散度
        # size_average不使用平均损失，而是返回总损失，(self.T ** 2)补偿温度缩放，/ y_s.shape[0]计算平均损失
        loss = F.kl_div(p_s, p_t, size_average=False) * (self.T ** 2) / y_s.shape[0]
        return loss

