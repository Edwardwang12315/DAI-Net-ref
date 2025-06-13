#-*- coding:utf-8 -*-

from __future__ import division
from __future__ import absolute_import
from __future__ import print_function


import torch
import torch.nn as nn
import torch.nn.init as init
from torch.autograd import Function
from torch.autograd import Variable



class L2Norm(nn.Module):
    # 使用L2范数对特征图进行归一化
    def __init__(self,n_channels, scale):
        super(L2Norm,self).__init__()
        self.n_channels = n_channels
        self.gamma = scale or None
        self.eps = 1e-10
        self.weight = nn.Parameter(torch.Tensor(self.n_channels))
        self.reset_parameters()

    def reset_parameters(self):
        init.constant(self.weight,self.gamma)

    def forward(self, x):
        norm = x.pow(2).sum(dim=1, keepdim=True).sqrt()+self.eps#平方和再开方，即计算L2范数
        #x /= norm
        x = torch.div(x,norm)#使用L2范数进行归一化处理
        # 先对权重进行维度变换，再对X进行处理
        out = self.weight.unsqueeze(0).unsqueeze(2).unsqueeze(3).expand_as(x) * x
        return out


