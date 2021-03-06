import os
from abc import ABCMeta, abstractmethod
import tensorflow as tf
import numpy as np

from Datasets.Dataset import batcher

'''
Implements models in an object-oriented way.

Contains code to generate a blank model, save and load models, and train models.

A pretrained model can also be partially loaded, and other components of it trained.
'''
class Model(metaclass=ABCMeta):
    def __init__(self, sess = None):
        self.layers = []
        if sess is None:
            sess = tf.Session()
        self.sess = sess
    def weight_variable(self, shape, initial=None):
        if initial is None:
            initial = tf.truncated_normal(shape, stddev=0.1)
        return tf.Variable(initial)

    def bias_variable(self, shape, initial=None):
      if initial is None:
          initial = tf.constant(0.1, shape=shape)
      return tf.Variable(initial)

    def conv2d(self, x, W):
      return tf.nn.conv2d(x, W, strides=[1, 1, 1, 1], padding='SAME')

    def max_pool_2x2(self, x):
      return tf.nn.max_pool(x, ksize=[1, 2, 2, 1],
                            strides=[1, 2, 2, 1], padding='SAME')

    def build_conv_layer(self, layer_input, input_channels, output_channels, initial_weights=None, initial_biases=None):
        patch_size = 5
        W_conv1 = self.weight_variable([patch_size, patch_size, input_channels, output_channels], initial_weights)
        b_conv1 = self.bias_variable([output_channels], initial_biases)

        h_conv1 = tf.nn.relu(self.conv2d(layer_input, W_conv1) + b_conv1)
        h_pool1 = self.max_pool_2x2(h_conv1)
        self.layers.append((h_pool1, W_conv1, b_conv1))
        return h_pool1, W_conv1, b_conv1

    def build_fully_connected_layer(self, layer_input, im_w, im_h, input_channels, num_neurons=1024, initial_weights=None, initial_biases=None):
        W_fc1 = self.weight_variable([im_w * im_h * input_channels, num_neurons], initial_weights)
        b_fc1 = self.bias_variable([num_neurons], initial_biases)

        h_fc1 = tf.nn.relu(tf.matmul(layer_input, W_fc1) + b_fc1)
        self.layers.append((h_fc1, W_fc1, b_fc1))
        return h_fc1, W_fc1, b_fc1

    def dropout(self, layer_input):
        keep_prob = tf.placeholder(tf.float32)
        h_fc1_drop = tf.nn.dropout(layer_input, keep_prob)
        return keep_prob, h_fc1_drop

    def build_readout_layer(self, layer_input, num_outputs, num_neurons=1024, initial_weights=None, initial_biases=None):
        W_fc2 = self.weight_variable([num_neurons, num_outputs], initial_weights)
        b_fc2 = self.bias_variable([num_outputs], initial_biases)

        #y_conv=tf.nn.softmax(tf.matmul(h_fc1_drop, W_fc2) + b_fc2)
        #y_conv=tf.matmul(h_fc1_drop, W_fc2) + b_fc2
        #y_conv=tf.nn.l2_normalize(tf.matmul(h_fc1_drop, W_fc2) + b_fc2, dim=1)
        y_raw=tf.matmul(layer_input, W_fc2) + b_fc2
        y_conv = tf.nn.sigmoid(y_raw)
        self.layers.append((y_conv, W_fc2, b_fc2))
        return y_conv, W_fc2, b_fc2

    @abstractmethod
    def build_graph(self, nn_im_w, nn_im_h, num_colour_channels=3):
        pass
    @abstractmethod
    def load(self, folder_path):
        pass
    @abstractmethod
    def save(self, folder_path):
        pass
    @abstractmethod
    def train(self, dataset):
        pass
    @abstractmethod
    def test(self, dataset):
        pass
    @abstractmethod
    def eval(self, image):
        pass

class BooleanModel(Model):
    '''
    Implements the boolean classifier (human or not human).
    See train_model_boolean.py
    '''
    def build_graph(self, nn_im_w, nn_im_h, num_colour_channels=3, weights=None, biases=None):
        num_outputs = 1 #ofc
        self.nn_im_w = nn_im_w
        self.nn_im_h = nn_im_h

        if weights is None:
            weights = [None, None, None, None, None]
        if biases is None:
            biases = [None, None, None, None, None]

        with tf.device('/cpu:0'):
            # Placeholder variables for the input image and output images
            self.x = tf.placeholder(tf.float32, shape=[None, nn_im_w*nn_im_h*3])
            self.y_ = tf.placeholder(tf.float32, shape=[None, num_outputs])
            self.threshold = tf.placeholder(tf.float32)

            # Build the convolutional and pooling layers
            conv1_output_channels = 32
            conv2_output_channels = 16
            conv3_output_channels = 8

            conv_layer_1_input = tf.reshape(self.x, [-1, nn_im_h, nn_im_w, num_colour_channels]) #The resized input image
            self.build_conv_layer(conv_layer_1_input, num_colour_channels, conv1_output_channels, initial_weights=weights[0], initial_biases=biases[0]) # layer 1
            self.build_conv_layer(self.layers[0][0], conv1_output_channels, conv2_output_channels, initial_weights=weights[1], initial_biases=biases[1])# layer 2
            self.build_conv_layer(self.layers[1][0], conv2_output_channels, conv3_output_channels, initial_weights=weights[2], initial_biases=biases[2])# layer 3

            # Build the fully connected layer
            convnet_output_w = nn_im_w//8
            convnet_output_h = nn_im_h//8

            fully_connected_layer_input = tf.reshape(self.layers[2][0], [-1, convnet_output_w * convnet_output_h * conv3_output_channels])
            self.build_fully_connected_layer(fully_connected_layer_input, convnet_output_w, convnet_output_h, conv3_output_channels, initial_weights=weights[3], initial_biases=biases[3])

            # The dropout stage and readout layer
            self.keep_prob, self.h_drop = self.dropout(self.layers[3][0])
            self.y_conv,_,_ = self.build_readout_layer(self.h_drop, num_outputs, initial_weights=weights[4], initial_biases=biases[4])

            self.mean_error =  tf.sqrt(tf.reduce_mean(tf.square(self.y_ - self.y_conv)))
            self.train_step = tf.train.AdamOptimizer(1e-4).minimize(self.mean_error)

            self.accuracy = (1.0 - tf.reduce_mean(tf.abs(self.y_ - tf.round(self.y_conv))))


            positive_examples = tf.greater_equal(self.y_, 0.5)
            negative_examples = tf.logical_not(positive_examples)
            positive_classifications = tf.greater_equal(self.y_conv, self.threshold)
            negative_classifications = tf.logical_not(positive_classifications)

            self.true_positive = tf.reduce_sum(tf.cast(tf.logical_and(positive_examples, positive_classifications),tf.int32)) # count the examples that are positive and classified as positive
            self.false_positive = tf.reduce_sum(tf.cast(tf.logical_and(negative_examples, positive_classifications),tf.int32)) # count the examples that are negative but classified as positive

            self.true_negative = tf.reduce_sum(tf.cast(tf.logical_and(negative_examples, negative_classifications),tf.int32)) # count the examples that are negative and classified as negative
            self.false_negative = tf.reduce_sum(tf.cast(tf.logical_and(positive_examples, negative_classifications),tf.int32)) # count the examples that are positive but classified as negative

            self.positive_count = tf.reduce_sum(tf.cast(positive_examples, tf.int32)) # count the examples that are positive
            self.negative_count = tf.reduce_sum(tf.cast(negative_examples, tf.int32)) # count the examples that are negative

            self.confusion_matrix = tf.reshape(tf.pack([self.true_positive, self.false_positive, self.false_negative, self.true_negative]), [2,2])

        self.sess.run(tf.initialize_all_variables())
    def load(self, folder_path, nn_im_w, nn_im_h, num_colour_channels=3):
        weights = []
        weights.append(np.load(os.path.join(folder_path, 'W1.npy')))
        weights.append(np.load(os.path.join(folder_path, 'W2.npy')))
        weights.append(np.load(os.path.join(folder_path, 'W3.npy')))
        weights.append(np.load(os.path.join(folder_path, 'W4.npy')))
        weights.append(np.load(os.path.join(folder_path, 'W5.npy')))

        biases = []
        biases.append(np.load(os.path.join(folder_path, 'b1.npy')))
        biases.append(np.load(os.path.join(folder_path, 'b2.npy')))
        biases.append(np.load(os.path.join(folder_path, 'b3.npy')))
        biases.append(np.load(os.path.join(folder_path, 'b4.npy')))
        biases.append(np.load(os.path.join(folder_path, 'b5.npy')))

        self.build_graph(nn_im_w, nn_im_h, num_colour_channels, weights=weights, biases=biases)
    def save(self, folder_path):
        if not os.path.exists(folder_path):
            os.mkdir(folder_path)
        np.save(os.path.join(folder_path, 'W1.npy'), self.sess.run(self.layers[0][1]))
        np.save(os.path.join(folder_path, 'W2.npy'), self.sess.run(self.layers[1][1]))
        np.save(os.path.join(folder_path, 'W3.npy'), self.sess.run(self.layers[2][1]))
        np.save(os.path.join(folder_path, 'W4.npy'), self.sess.run(self.layers[3][1]))
        np.save(os.path.join(folder_path, 'W5.npy'), self.sess.run(self.layers[4][1]))

        # Biases
        np.save(os.path.join(folder_path, 'b1.npy'), self.sess.run(self.layers[0][2]))
        np.save(os.path.join(folder_path, 'b2.npy'), self.sess.run(self.layers[1][2]))
        np.save(os.path.join(folder_path, 'b3.npy'), self.sess.run(self.layers[2][2]))
        np.save(os.path.join(folder_path, 'b4.npy'), self.sess.run(self.layers[3][2]))
        np.save(os.path.join(folder_path, 'b5.npy'), self.sess.run(self.layers[4][2]))
    def train(self, train_dataset):
        batch_size = 50
        num_images = len(train_dataset)
        for batch_no, batch in enumerate(train_dataset.iter_batches(self.nn_im_w, self.nn_im_h, 1,1, batch_size=batch_size)):
            train_accuracy = self.accuracy.eval(feed_dict={
                self.x:batch[0], self.y_: batch[1], self.keep_prob: 1.0})
            if batch_no % 5 == 0:
                print("%.0f%%, training accuracy %g"%(100*batch_no*batch_size/num_images, train_accuracy))
                # r = y_conv.eval(feed_dict={self.x: batch[0], keep_prob: 1.0})
                # print('Guess: ',  np.round(r.flatten()))
                # print('Actual:', np.round(batch[1].flatten()))
            self.train_step.run(feed_dict={self.x: batch[0], self.y_: batch[1], self.keep_prob: 0.5})
    def test(self, dataset_iter, threshold=0.5):
        cum_accuracy = 0
        num_batches = 0

        confusion_matrix = np.zeros((2,2,))
        for batch in batcher(dataset_iter, batch_size=10):
            cum_accuracy += self.accuracy.eval(feed_dict={
                self.x: batch[0], self.y_: batch[1], self.keep_prob: 1.0})
            confusion_matrix += self.confusion_matrix.eval(feed_dict={
                self.x: batch[0], self.y_: batch[1], self.keep_prob: 1.0, self.threshold: threshold})
            num_batches += 1
        mean_accuracy = cum_accuracy/num_batches

        return mean_accuracy, confusion_matrix
    def ROC(self, dataset_iter, threshold_step=0.1):
        TPs = [0 for i in range(int(1/threshold_step)+1)]
        FPs = [0 for i in range(int(1/threshold_step)+1)]
        positive_count = 0
        negative_count = 0
        for batch in batcher(dataset_iter, batch_size=100):
            # The number of positive examples in this batch
            positive_count += self.positive_count.eval(feed_dict={
                self.x: batch[0], self.y_: batch[1], self.keep_prob: 1.0})
            # The number of negative examples in the batch
            negative_count += self.negative_count.eval(feed_dict={
                self.x: batch[0], self.y_: batch[1], self.keep_prob: 1.0})

            threshold = 0.0
            index = 0
            while threshold <= 1.0:
                TPs[index] += self.true_positive.eval(feed_dict={
                    self.x: batch[0], self.y_: batch[1], self.keep_prob: 1.0, self.threshold: threshold})
                FPs[index] += self.false_positive.eval(feed_dict={
                    self.x: batch[0], self.y_: batch[1], self.keep_prob: 1.0, self.threshold: threshold})

                threshold += threshold_step
                index += 1

        return [tp/positive_count for tp in TPs], [fp/negative_count for fp in FPs]
    def eval(self, image):
        return self.y_conv.eval(feed_dict={self.x: image, self.keep_prob: 1.0})
