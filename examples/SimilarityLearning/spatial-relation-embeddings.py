#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: mnist-embeddings.py
# Author: PatWie <mail@patwie.com>
import numpy as np
import os

from tensorpack import *
import tensorpack.tfutils.symbolic_functions as symbf
from tensorpack.tfutils.summary import add_moving_summary
import argparse
import tensorflow as tf
import tensorflow.contrib.slim as slim

from spatial_relations_data import get_test_data, Sun09Pairs, Sun09Triplets

MATPLOTLIB_AVAIBLABLE = False
try:
    import matplotlib
    from matplotlib import offsetbox
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    plt.switch_backend('agg')
    MATPLOTLIB_AVAIBLABLE = True
except ImportError:
    MATPLOTLIB_AVAIBLABLE = False


class EmbeddingModel(ModelDesc):
    def embed(self, x, nfeatures=2):
        """Embed all given tensors into an nfeatures-dim space.  """
        list_split = 0
        if isinstance(x, list):
            list_split = len(x)
            x = tf.concat(x, 0)

        # pre-process MNIST dataflow data
        #x = tf.expand_dims(x, 3)
        #x = x * 2 - 1

        # the embedding network
        #net = slim.layers.conv2d(x, 20, 5, scope='conv1')
        #net = slim.layers.max_pool2d(net, 2, scope='pool1')
        #net = slim.layers.conv2d(net, 50, 5, scope='conv2')
        #net = slim.layers.max_pool2d(net, 2, scope='pool2')
        #net = slim.layers.flatten(net, scope='flatten3')
        #net = slim.layers.fully_connected(net, 500, scope='fully_connected4')
        #embeddings = slim.layers.fully_connected(net, nfeatures, activation_fn=None, scope='fully_connected5')

        with slim.arg_scope([slim.layers.fully_connected], weights_regularizer=slim.l2_regularizer(1e-5)):
            net = slim.layers.conv2d(x, 64, [3, 3], scope='conv1')
            net = slim.layers.max_pool2d(net, [2, 2], scope='pool1')
            net = slim.layers.conv2d(net, 128, [3, 3], scope='conv2')
            net = slim.layers.max_pool2d(net, [2, 2], scope='pool2')
            net = slim.layers.conv2d(net, 256, [3, 3], scope='conv3')
            net = slim.layers.max_pool2d(net, [2, 2], scope='pool3')
            net = slim.layers.conv2d(net, 512, [3, 3], scope='conv4')
            net = slim.layers.max_pool2d(net, [2, 2], scope='pool4')
            net = slim.layers.conv2d(net, 512, [3, 3], scope='conv5')
            net = slim.layers.max_pool2d(net, [2, 2], scope='pool5')
            net = slim.layers.flatten(net, scope='flatten5')
            net = slim.layers.fully_connected(net, 4096, scope='fc6')
            net = slim.layers.dropout(net, 0.5, scope='dropout6')
            net = slim.layers.fully_connected(net, 4096, scope='fc7')
            net = slim.layers.dropout(net, 0.5, scope='dropout7')
            embeddings = slim.layers.fully_connected(net, nfeatures, activation_fn=None, scope='fc8')


        # if "x" was a list of tensors, then split the embeddings
        if list_split > 0:
            embeddings = tf.split(embeddings, list_split, 0)

        return embeddings

    def _get_optimizer(self):
        lr = symbf.get_scalar_var('learning_rate', 1e-4, summary=True)
        return tf.train.GradientDescentOptimizer(lr)


class SiameseModel(EmbeddingModel):
    @staticmethod
    def get_data():
        ds = Sun09Pairs('data/train.txt','train')
        ds = AugmentImageComponent(ds, [imgaug.Resize((224, 224))])
        ds = BatchData(ds, 64 // 2)
        return ds

    def _get_inputs(self):
        return [InputDesc(tf.float32, (None, 224, 224), 'input'),
                InputDesc(tf.float32, (None, 224, 224), 'input_y'),
                InputDesc(tf.int32, (None,), 'label')]

    def _build_graph(self, inputs):
        # get inputs
        x, y, label = inputs
        # embed them
        x, y = self.embed([x, y])

        # tag the embedding of 'input' with name 'emb', just for inference later on
        with tf.variable_scope(tf.get_variable_scope(), reuse=True):
            tf.identity(self.embed(inputs[0]), name="emb")

        # compute the actual loss
        cost, pos_dist, neg_dist = symbf.contrastive_loss(x, y, label, 5., extra=True, scope="loss")
        self.cost = tf.identity(cost, name="cost")

        # track these values during training
        add_moving_summary(pos_dist, neg_dist, self.cost)


class CosineModel(SiameseModel):
    def _build_graph(self, inputs):
        x, y, label = inputs
        x, y = self.embed([x, y])

        with tf.variable_scope(tf.get_variable_scope(), reuse=True):
            tf.identity(self.embed(inputs[0]), name="emb")

        cost = symbf.siamese_cosine_loss(x, y, label, scope="loss")
        self.cost = tf.identity(cost, name="cost")
        add_moving_summary(self.cost)


class TripletModel(EmbeddingModel):
    @staticmethod
    def get_data():
        ds = Sun09Triplets('data/train.txt','train')
        ds = AugmentImageComponent(ds, [imgaug.Resize((224, 224))])
        ds = BatchData(ds, 64 // 3)
        return ds

    def _get_inputs(self):
        return [InputDesc(tf.float32, (None, 224, 224, 3), 'input'),
                InputDesc(tf.float32, (None, 224, 224, 3), 'input_p'),
                InputDesc(tf.float32, (None, 224, 224, 3), 'input_n')]

    def loss(self, a, p, n):
        return symbf.triplet_loss(a, p, n, 5., extra=True, scope="loss")

    def _build_graph(self, inputs):
        a, p, n = inputs
        a, p, n = self.embed([a, p, n])

        with tf.variable_scope(tf.get_variable_scope(), reuse=True):
            tf.identity(self.embed(inputs[0]), name="emb")

        cost, pos_dist, neg_dist = self.loss(a, p, n)

        self.cost = tf.identity(cost, name="cost")
        add_moving_summary(pos_dist, neg_dist, self.cost)


class SoftTripletModel(TripletModel):
    def loss(self, a, p, n):
        return symbf.soft_triplet_loss(a, p, n, scope="loss")


def get_config(model, algorithm_name):

    extra_display = ["cost"]
    if not algorithm_name == "cosine":
        extra_display = extra_display + ["loss/pos-dist", "loss/neg-dist"]

    return TrainConfig(
        dataflow=model.get_data(),
        model=model(),
        callbacks=[
            ModelSaver(),
            ScheduledHyperParamSetter('learning_rate', [(10, 1e-5), (20, 1e-6)])
        ],
        extra_callbacks=[
            MovingAverageSummary(),
            ProgressBar(extra_display),
            MergeAllSummaries(),
            RunUpdateOps()
        ],
        max_epoch=10000,
    )


def visualize(model_path, model, algo_name):
    if not MATPLOTLIB_AVAIBLABLE:
        logger.error("visualize requires matplotlib package ...")
        return
    pred = OfflinePredictor(PredictConfig(
        session_init=get_model_loader(model_path),
        model=model(),
        input_names=['input'],
        output_names=['emb']))

    NUM_BATCHES = 6
    BATCH_SIZE = 64
    #images = np.zeros((BATCH_SIZE * NUM_BATCHES, 224, 224))  # the used digits
    embed = np.zeros((BATCH_SIZE * NUM_BATCHES, 2))  # the actual embeddings in 2-d
    labels = np.zeros((BATCH_SIZE * NUM_BATCHES)) # true labels

    # get only the embedding model data (MNIST test)
    ds = get_test_data('data/train.txt')
    ds.reset_state()

    for offset, dp in enumerate(ds.get_data()):
        img, label = dp
        prediction = pred([img])[0]
        embed[offset * BATCH_SIZE:offset * BATCH_SIZE + BATCH_SIZE, ...] = prediction
        #images[offset * BATCH_SIZE:offset * BATCH_SIZE + BATCH_SIZE, ...] = digit
        labels[offset * BATCH_SIZE:offset * BATCH_SIZE + BATCH_SIZE, ...] = label
        offset += 1
        if offset == NUM_BATCHES:
            break

    print('MATPLOTLIB_AVAILABLE: '+str(MATPLOTLIB_AVAIBLABLE))
    plt.ioff()
    fig = plt.figure()
    ax = plt.subplot(111)
    ax_min = np.min(embed, 0)
    ax_max = np.max(embed, 0)

    ax_dist_sq = np.sum((ax_max - ax_min)**2)
    ax.axis('off')

    # dictionary of labels
    relation_labels = {0:'below', 1:'across from', 2:'under', 3:'left of', 4:'behind', 
            5:'on', 6:'right of', 7:'in', 8:'in front of', 9:'above'}
    circles = []
    classes = []
    c = ['r','g','b','c','yellow','blueviolet','lightblue','darkgreen','orange','brown']

    for i in relation_labels:
        circles.append(mpatches.Circle((0,0),1,color=c[i]))
        classes.append(relation_labels[i])

    shown_images = np.array([[1., 1.]])
    for i in range(embed.shape[0]):
        dist = np.sum((embed[i] - shown_images)**2, 1)
        if np.min(dist) < 3e-4 * ax_dist_sq:     # don't show points that are too close
            continue
        shown_images = np.r_[shown_images, [embed[i]]]
        plt.scatter(embed[i][0], embed[i][1], color=c[int(labels[i])])
        #imagebox = offsetbox.AnnotationBbox(offsetbox.OffsetImage(np.reshape(images[i, ...], [224, 224]),
        #                                    zoom=0.6, cmap=plt.cm.gray_r), xy=embed[i], frameon=False)
        #ax.add_artist(imagebox)

    plt.axis([ax_min[0]*2, ax_max[0]*2, ax_min[1]*2, ax_max[1]*2])
    plt.xticks([]), plt.yticks([])
    plt.legend(circles, classes, loc='lower left')
    plt.title('Embedding using %s-loss' % algo_name)
    plt.savefig('%s.jpg' % algo_name)
    plt.close(fig)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--gpu', help='comma separated list of GPU(s) to use.')
    parser.add_argument('--load', help='load model')
    parser.add_argument('-a', '--algorithm', help='used algorithm', type=str,
                        choices=["siamese", "cosine", "triplet", "softtriplet"])
    parser.add_argument('--visualize', help='export embeddings into an image', action='store_true')
    args = parser.parse_args()

    ALGO_CONFIGS = {"siamese": SiameseModel,
                    "cosine": CosineModel,
                    "triplet": TripletModel,
                    "softtriplet": SoftTripletModel}

    logger.auto_set_dir(name=args.algorithm)

    with change_gpu(args.gpu):
        if args.visualize:
            visualize(args.load, ALGO_CONFIGS[args.algorithm], args.algorithm)
        else:
            config = get_config(ALGO_CONFIGS[args.algorithm], args.algorithm)
            if args.load:
                config.session_init = SaverRestore(args.load)
            else:
                SimpleTrainer(config).train()
