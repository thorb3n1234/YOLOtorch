from __future__ import division

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np
from util import *


class EmptyLayer(nn.Module):
    def __init__(self):
        super(EmptyLayer, self).__init__()


class DetectionLayer(nn.Module):
    def __init__(self, anchors):
        super(DetectionLayer, self).__init__()
        self.anchors = anchors


class Darknet(nn.Module):
    def __init__(self, cfgfile):
        super(Darknet, self).__init__()
        self.blocks = parse_cfg(cfgfile)
        self.net_info, self.module_list = create_modules(self.blocks)


def get_test_input():
    img = cv2.imread("dog-cycle-car.png")
    img = cv2.resize(img, (416, 416))
    img_ = img[:, :, ::-1].transpose((2, 0, 1))  # BGR -> RGB | H X W C -> C X H X W
    img_ = img_[np.newaxis, :, :, :] / 255.0  # Add a channel at 0 (for batch) | Normalise
    img_ = torch.from_numpy(img_).float()  # Convert to float
    img_ = Variable(img_)  # Convert to Variable
    return img_


def forward(self, x, CUDA):
    modules = self.blocks[1:]
    outputs = {}

    write = 0
    for i, module in enumerate(modules):
        module_type = module["type"]
        if module_type == "convolutional" or module_type == "upsample":
            x = self.module_list[i](x)
        elif module_type == "route":
            layers = module["layers"]
            layers = [int(a) for a in layers]

            if layers[0] > 0:
                layers[0] = layers[0] - i
            if len(layers) == 1:
                x = outputs[i + layers[0]]
            else:
                if layers[1] > 0:
                    layers[1] = layers[1] - i

                map1 = outputs[i + layers[0]]
                map2 = outputs[i + layers[1]]

                x = torch.cat((map1, map2), 1)

        elif module_type == "shortcut":
            from_ = int(module["from"])
            x = outputs[i - 1] + outputs[i + from_]
        elif module_type == "yolo":

            anchors = self.module_list[i][0].anchors

            inp_dim = int(self.net_info["height"])

            num_classes = int(module["classes"])

            x = x.data
            x = predict_transform(x, inp_dim, anchors, num_classes, CUDA)

            if not write:
                detections = x
                write = 1
            else:
                detections = torch.cat((detections, x), 1)

        outputs[i] = x

    return detections


def parse_cfg(cfgfile):
    #   read lines in file
    file = open(cfgfile, 'r')
    lines = file.read().split('\n')
    lines = [x for x in lines if len(x) > 0]
    lines = [x for x in lines if x[0] != '#']
    lines = [x.rstrip().lstrip() for x in lines]

    block = {}
    blocks = []
    for line in lines:
        if line[0] == '[':
            if (len(block)) != 0:
                blocks.append(block)
                block = {}
            block["type"] = line[1:-1].rstrip()
        else:
            key, value = line.split("=")
            block[key.rstrip()] = value.lstrip()
    blocks.append(block)

    return blocks


def create_modules(blocks):
    net_info = blocks[0]
    module_list = nn.ModuleList()
    prev_filters = 3
    output_filters = []

    for index, x in enumerate(blocks[1:]):
        module = nn.Sequential()

        if x["type"] == "convolutional":
            activation = x["activation"]
            try:
                batch_normalize = int(x["batch_normalize"])
                bias = False
            except:
                batch_normalize = 0
                bias = True
            filters = int(x["filters"])
            padding = int(x["pad"])
            kernel_size = int(x["size"])
            stride = int(x["stride"])

            if padding:
                pad = (kernel_size - 1) // 2
            else:
                pad = 0

            # add convolutional alyer
            conv = nn.Conv2d(prev_filters, filters, kernel_size, stride, pad, bias=bias)
            module.add_module("conv_{}".format(index), conv)

            # add norm batch layer
            if batch_normalize:
                bn = nn.BatchNorm2d(filters)
                module.add_module("batch_norm{}".format(index), bn)

                # Check the activation.
                # It is either Linear or a Leaky ReLU for YOLO
                if activation == "leaky":
                    activn = nn.LeakyReLU(0.1, inplace=True)
                    module.add_module("leaky_{0}".format(index), activn)

                # If it's an upsampling layer
                # We use Bilinear2dUpsampling
        elif x["type"] == "upsample":
            stride = int(x["stride"])
            upsample = nn.Upsample(scale_factor=2, mode="bilinear")
            module.add_module("upsample_{}".format(index), upsample)
        elif (x["type"] == "route"):
            x["layers"] = x["layers"].split(',')
            # Start  of a route
            start = int(x["layers"][0])
            # end, if there exists one.
            try:
                end = int(x["layers"][1])
            except:
                end = 0
            # Positive anotation
            if start > 0:
                start = start - index
            if end > 0:
                end = end - index
                route = EmptyLayer()
                module.add_module("route_{0}".format(index), route)
            if end < 0:
                filters = output_filters[index + start] + output_filters[index + end]
            else:
                filters = output_filters[index + start]
        # shortcut corresponds to skip connection
        elif x["type"] == "shortcut":
            shortcut = EmptyLayer()
            module.add_module("shortcut_{}".format(index), shortcut)
        # YOLO layer
        elif x["type"] == "yolo":
            mask = x["mask"].split(",")
            mask = [int(x) for x in mask]

            anchors = x["anchors"].split(',')
            anchors = [int(x) for x in anchors]
            anchors = [(anchors[i], anchors[i + 1]) for i in range(0, len(anchors), 2)]
            anchors = [anchors[i] for i in mask]

            detection = DetectionLayer(anchors)
            module.add_module("Detection_{}".format(index), detection)
        module_list.append(module)
        prev_filters = filters
        output_filters.append(filters)

    return net_info, module_list


model = Darknet("cfg/yolov3.cfg")
inp = get_test_input()
pred = forward(model, inp, torch.cuda.is_available())
print(pred.shape)
print(pred)

