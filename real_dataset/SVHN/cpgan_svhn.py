import pandas 
import os 
import time
import random
import math
import matplotlib.pyplot as plt 
import numpy as np 
from numpy.linalg import pinv 
from scipy.io import loadmat
from scipy.misc import imrotate , imread , imsave
import tensorflow as tf 
import tensorflow.contrib.layers as ly
from tensorflow.python.framework import constant_op
from tensorflow.python.ops import math_ops
from tensorflow.python.framework import dtypes
from sklearn.metrics import mean_squared_error
from sklearn.metrics.pairwise import rbf_kernel
from sklearn.utils import check_random_state
from sklearn.kernel_approximation import RBFSampler
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

plt.switch_backend('agg')
class wrs:
    def __init__(self,arg):

        self.arg = arg
        self.t_data, self.v_data, self.te_data, self.t_label, self.v_label, self.te_label = self.load_data()

        self.gamma = self.arg.gamma
        self.mapping_dim = self.arg.mapping_dim
        self.seed = self.arg.seed        
        self.batch_size = self.arg.batch_size
        self.lr = 0.001

        assert len(self.t_data) == len(self.t_label), 'Ensure training data size'
        assert len(self.v_data) == len(self.v_label), 'Ensure validation data size'
        assert len(self.te_data) == len(self.te_label), 'Ensure testing data size'
        self.build_model()

        print("The number of multiplication and addtion : {} and {}.".format(self.g_multiplication,self.g_addition))
        print("The number of multiplication and addtion : {} and {}.".format(self.c_multiplication,self.c_addition))

        self.init_learning_rate = 0.01
        num_steps_per_epoch = len(self.t_data) // self.batch_size
        self.num_steps = 160 * num_steps_per_epoch
        ####### 


    def preprocess(self,img):
        svhn_mean = np.array([x / 255.0 for x in[109.9, 109.7, 113.8]])
        svhn_std = np.array([x / 255.0 for x in [50.1, 50.6, 50.8]])
        img = img/255
        img = img - svhn_mean
        img = img / svhn_std
        return img

    def load_data(self):
        svhn_mean = np.array([x / 255.0 for x in[109.9, 109.7, 113.8]])
        svhn_std = np.array([x / 255.0 for x in [50.1, 50.6, 50.8]])
        temp = loadmat('svhn/train_32x32.mat')
        t_data = temp['X'].astype("float32")
        t_label = temp['y']
        a = []
        b = []
        for i in range(t_data.shape[3]) : 
            te = self.preprocess(t_data[:,:,:,i])
            a.append(te)
            b.append(t_label[i][0]-1)

        temp = loadmat('svhn/test_32x32.mat')
        te_data = temp['X'].astype("float32")
        te_label = temp['y']
        c = []
        d = []
        for i in range(te_data.shape[3]) : 
            te = self.preprocess(te_data[:,:,:,i])
            c.append(te)
            d.append(te_label[i][0]-1)    

        temp = loadmat('svhn/extra_32x32.mat')
        temp_1 = temp['X'].astype("float32")
        temp_2 = temp['y']
        e = []
        f = []
        for i in range(temp_1.shape[3]):
            te = self.preprocess(temp_1[:,:,:,i])
            e.append(te)
            f.append(temp_2[i][0]-1)   
        a = a + e 
        b = b + f
        t_img, val_img, t_label, val_label = train_test_split(a, b, test_size=0.2, random_state=9, shuffle=False)
        return t_img, val_img, c, t_label, val_label, d

    def wideres33block(self,X,N,K,iw,bw,s,scope):
        
        # Creates N no. of 3,3 type residual blocks with dropout that consitute the conv2/3/4 blocks
        # with widening factor K and X as input. s is stride and bw is base width (no. of filters before multiplying with k)
        # iw is input width.
        # (see https://arxiv.org/abs/1605.07146 paper for details on the block)
        # In this case, dropout = probability to keep the neuron enabled.
        # phase = true when training, false otherwise.
        
        with tf.variable_scope(scope):
            X = self.bo_batch_norm(X, self.is_train)
            conv33_1 = ly.conv2d(X, kernel_size=3, num_outputs=bw*K, padding='SAME', stride=s, activation_fn=None, biases_initializer=None)
            conv33_1 = self.bo_batch_norm(conv33_1,self.is_train)
            conv33_1 = tf.nn.dropout(conv33_1,keep_prob = self.dropout)
            
            conv33_2 = ly.conv2d(conv33_1,kernel_size=3,num_outputs=bw*K,stride=1,activation_fn=None, biases_initializer=None)
            conv_skip= ly.conv2d(X, kernel_size=1, num_outputs=bw*K, stride=s,padding='VALID', activation_fn=None, biases_initializer=None) #shortcut connection

            caddtable = tf.add(conv33_2,conv_skip)
            
            #1st of the N blocks for conv2/3/4 block ends here. The rest of N-1 blocks will be implemented next with a loop.

            for i in range(0,N-1):
                
                C = caddtable
                Cactivated = self.bo_batch_norm(C,self.is_train)
                
                conv33_1 = ly.conv2d(Cactivated, kernel_size=3, num_outputs=bw*K, stride=1, activation_fn=None, biases_initializer=None)
                conv33_1 = self.bo_batch_norm(conv33_1,self.is_train)
                conv33_1 = tf.nn.dropout(conv33_1,self.dropout)
                conv33_2 = ly.conv2d(conv33_1, kernel_size=3, num_outputs=bw*K, stride=1, activation_fn=None, biases_initializer=None)
                caddtable = tf.add(conv33_2,C)
        return caddtable #out 

    def WRN(self,x,layers,K):#,scope): #Wide residual network

        # 1 conv + 3 convblocks*(3 conv layers *1 group for each block + 2 conv layers*(N-1) groups for each block [total 1+N-1 = N groups]) = layers
        # 3*2*(N-1) = layers - 1 - 3*3
        # N = (layers -10)/6 + 1
        # So N = (layers-4)/6

        widing_factor = 8
        filters = [16, 16*widing_factor, 32*widing_factor, 64*widing_factor]
        strides = [1, 2, 2]
        N = int((layers-4)/6)
        with tf.variable_scope('utility_classifier'):
            conv1 = ly.conv2d(x, kernel_size=3, num_outputs=16, padding='SAME', stride=1, activation_fn=None, biases_initializer=None, weights_initializer=tf.contrib.layers.xavier_initializer())
            #conv1 = self.bo_batch_norm(conv1,self.is_train)
            conv2 = self.wideres33block(conv1, N, K, 16, 16, 1, 'conv2')
            conv3 = self.wideres33block(conv2, N, K, 16*K, 32, 2, 'conv3')
            conv4 = self.wideres33block(conv3, N, K, 32*K, 64, 2, 'conv4')
            #conv4 = self.bo_batch_norm(conv4, self.is_train)
            #conv2 = self.wideres33block(conv1, filters[0], filters[1], strides[0], N, 'conv2')
            #conv3 = self.wideres33block(conv2, filters[1], filters[2], strides[1], N, 'conv3')
            #conv4 = self.wideres33block(conv3, filters[2], filters[3], strides[2], N, 'conv4')
            conv4 = self.bo_batch_norm(conv4, self.is_train) 
            pooled = tf.nn.avg_pool(conv4, ksize=[1,8,8,1], strides=[1,1,1,1], padding='VALID')
            
            #Initialize weights and biases for fully connected layers
            #with tf.variable_scope(scope+"regularize",reuse=False):
            #   wd1 = tf.Variable(tf.truncated_normal([1*1*64*K,64*K],stddev=5e-2))
            #    wout = tf.Variable(tf.truncated_normal([64*K, n_classes]))
            #bd1 = tf.Variable(tf.constant(0.1,shape=[64*K]))
            #bout = tf.Variable(tf.constant(0.1,shape=[n_classes]))

            # Fully connected layer
            # Reshape pooling layer output to fit fully connected layer input
            #wd1 = tf.Variable(tf.truncated_normal([1*1*64*K,64*K],stddev=5e-2))
            #sha = pooled.get_shape().as_list()
            #sha = (sha[1],sha[2],sha[3])
            #fc1 = tf.reshape(pooled, [-1, wd1.get_shape().as_list()[0]])   

            x_shape = pooled.get_shape().as_list()
                #x = tf.reshape(x, [-1, x_shape[1]])
            print(x_shape)
            fc1 = tf.reshape(pooled, [-1, x_shape[-1]])
            #fc1 = ly.flatten(pooled)
            with tf.variable_scope('logits'):
                #fc1 = ly.fully_connected(fc1,64*K,activation_fn=tf.nn.relu)
                #fc1 = tf.add(tf.matmul(fc1, wd1), bd1)
                #fc1 = tf.nn.elu(fc1)
                # Output, class prediction
                #out = tf.add(tf.matmul(fc1, wout), bout)
                out = ly.fully_connected(fc1, 10, activation_fn=None, weights_initializer=tf.contrib.layers.xavier_initializer())
        return out


    def wrs_16_2(self,img):
        #widing_factor = 2
        widing_factor = 8
        num_residual_units = 2 # N = (deep -4 /6)
        print('Building model')
        # Init. conv.
        x = ly.conv2d(img, kernel_size=3, num_outputs=16, stride=1, activation_fn=None, weights_initializer=tf.contrib.layers.xavier_initializer())
        self.c_addition = 0
        self.c_multiplication = 0
        # Residual Blocks
        filters = [16, 16*widing_factor, 32*widing_factor, 64*widing_factor]
        strides = [1, 2, 2]
        with tf.variable_scope('utility_classifier'):
            for i in range(1, 4):
                # First residual unit
                with tf.variable_scope('unit_%d_0' % i) as scope:
                    print('\tBuilding residual unit: %s' % scope.name)
                    x = self.bo_batch_norm(x ,self.is_train)
                    self.c_addition +=1 
                    self.c_multiplication +=1
                    # Shortcut
                    if filters[i-1] == filters[i]:
                        if strides[i-1] == 1:
                            shortcut = tf.identity(x)
                        else:
                            #shortcut = ly.conv2d(x, kernel_size=1,num_outputs=bw*K,stride=s,activation_fn=None) #shortcut connection
                            shortcut = tf.nn.max_pool(x, [1, strides[i-1], strides[i-1], 1],
                                                      [1, strides[i-1], strides[i-1], 1], 'VALID')
                    else:
                        #shortcut = utils._conv(x, 1, filters[i], strides[i-1], name='shortcut')
                        channel = x.get_shape().as_list()[-1]
                        shortcut = ly.conv2d(x,kernel_size=1, num_outputs=filters[i], stride=strides[i-1])
                        temp = shortcut.get_shape().as_list()
                        self.c_addition += (temp[1]*temp[2]*temp[3]*1*1*channel)
                        self.c_multiplication += (temp[1]*temp[2]*temp[3]*1*1*channel)
                        #self.output_c.append(x)
                    # Residual

                    channel = x.get_shape().as_list()[-1]
                    x = ly.conv2d(x, kernel_size=3, num_outputs=filters[i], stride=strides[i-1],activation_fn=None, biases_initializer=None, weights_initializer=tf.contrib.layers.xavier_initializer())
                    temp = x.get_shape().as_list()
                    self.c_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
                    self.c_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel) 

                    x = self.bo_batch_norm(x, self.is_train)

                    self.c_addition +=1 
                    self.c_multiplication +=1

                    x = tf.nn.dropout(x,keep_prob=self.dropout)

                    channel = x.get_shape().as_list()[-1]
                    x = ly.conv2d(x, kernel_size=3, num_outputs=filters[i], stride=1,activation_fn=None, biases_initializer=None, weights_initializer=tf.contrib.layers.xavier_initializer())
                    temp = x.get_shape().as_list()
                    self.c_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
                    self.c_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel) 

                    # Merge
                    x = x + shortcut
                    self.c_addition += 1
                # Other residual units
                for j in range(1,num_residual_units):
                    with tf.variable_scope('unit_%d_%d' % (i, j)) as scope:
                        print('\tBuilding residual unit: %s' % scope.name)
                        # Shortcut
                        shortcut = x
                        # Residual
                        x = self.bo_batch_norm(x, self.is_train)

                        self.c_addition +=1 
                        self.c_multiplication +=1

                        channel = x.get_shape().as_list()[-1]

                        x = ly.conv2d(x, kernel_size=3, num_outputs=filters[i], stride=1, activation_fn=None, biases_initializer=None, weights_initializer=tf.contrib.layers.xavier_initializer())
                        temp = x.get_shape().as_list()
                        self.c_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
                        self.c_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel) 

                        x = self.bo_batch_norm(x, self.is_train)

                        self.c_addition +=1 
                        self.c_multiplication +=1

                        x = tf.nn.dropout(x,keep_prob=self.dropout)

                        channel = x.get_shape().as_list()[-1]
                        x = ly.conv2d(x, kernel_size=3, num_outputs=filters[i], stride=1, activation_fn=None, biases_initializer=None, weights_initializer=tf.contrib.layers.xavier_initializer())
                        temp = x.get_shape().as_list()
                        self.c_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
                        self.c_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel)          
                        # Merge
                        x = x + shortcut

                        self.c_addition += 1 


                #x = self.bo_batch_norm(x, self.is_train)

            # Last unit
            with tf.variable_scope('unit_last') as scope:
                print('\tBuilding unit: %s' % scope.name)
                x = self.bo_batch_norm(x, self.is_train)

                self.c_addition +=1 
                self.c_multiplication +=1

                x = tf.nn.avg_pool(x,ksize=[1,8,8,1], strides=[1,1,1,1], padding='VALID')
                #sha = x.get_shape().as_list()
                #fc1 = tf.reshape(x, [-1, sha[1]])  
                #x = tf.reduce_mean(x, [1, 2])

            # Logit
            with tf.variable_scope('logits') as scope:
                print('\tBuilding unit: %s' % scope.name)
                x_shape = x.get_shape().as_list()
                #x = tf.reshape(x, [-1, x_shape[1]])
                
                self.x = tf.reshape(x, [-1, x_shape[-1]])
                x = ly.fully_connected(self.x, 10, activation_fn=None, weights_initializer=tf.contrib.layers.xavier_initializer())

                self.c_addition += (x_shape[-1]*10)
                self.c_multiplication += (x_shape[-1]*10)

        return x

    def bo_batch_norm(self,x, is_training, momentum=0.99, epsilon=0.00001):#epsilon=0.00001
        """
        Add a new batch-normalization layer.
        :param x: tf.Tensor, shape: (N, H, W, C).
        :param is_training: bool, train mode : True, test mode : False
        :return: tf.Tensor.
        """
        x = tf.layers.batch_normalization(x, momentum=momentum, epsilon=epsilon,training=is_training)
        #x = tf.layers.batch_normalization(x, training=is_training)
        x = tf.nn.relu(x)
        return x
    

    def init_tensor(self, shape):
        return tf.Variable(tf.truncated_normal(shape, mean=0.0, stddev=1.0))

    def _conv(self, input, filter_shape, stride):
        """Convolutional layer"""
        return tf.nn.conv2d(input,
                            filter=self.init_tensor(filter_shape),
                            strides=[1, stride, stride, 1],
                            padding="SAME")

    def _residual_unit(self, input_, in_filters, out_filters, stride, option=0):
        """
        Residual unit with 2 sub-layers
        When in_filters != out_filters:
        option 0: zero padding
        """
        # first convolution layer
        x = self.bo_batch_norm(input_,self.is_train)

        self.g_addition += 1 
        self.g_multiplication += 1

        x = tf.nn.relu(x)

        channel = x.get_shape().as_list()[-1]
        x = self._conv(x, [3, 3, in_filters, out_filters], stride)

        temp = x.get_shape().as_list()
        self.g_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
        self.g_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel) 

        # second convolution layer
        x = self.bo_batch_norm(x,self.is_train)

        self.g_addition += 1 
        self.g_multiplication += 1

        x = tf.nn.relu(x)
        channel = x.get_shape().as_list()[-1]
        x = self._conv(x, [3, 3, out_filters, out_filters], stride)

        self.g_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
        self.g_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel) 

        if in_filters != out_filters:
            if option == 0:
                difference = out_filters - in_filters
                left_pad = difference / 2
                right_pad = difference - left_pad
                identity = tf.pad(input_, [[0, 0], [0, 0], [0, 0], [left_pad, right_pad]])
                self.g_addition += 1 
                return x + identity
            else:
                print("Not implemented error")
                exit(1)
        else:
            self.g_addition += 1 
            return x + input_

    def residual_g(self,image,reuse=False):
        stride = [1,1,1]
        filter_size = [3,3,3]

        self.g_addition = 0 
        self.g_multiplication = 0

        with tf.variable_scope('compressor') as scope:
            if reuse : 
                scope.reuse_variables()
            channel = image.get_shape().as_list()[-1] 
            x = self._conv(image, [3, 3, 3, 3], 1)  
            temp = x.get_shape().as_list()

            self.g_addition += (temp[1]*temp[2]*temp[3]*3*3*channel)
            self.g_multiplication += (temp[1]*temp[2]*temp[3]*3*3*channel) 


            for i in range(len(filter_size)):
                for j in range(len([3,3,3])):
                    #with tf.variable_scope('unit_%d_sublayer_%d' % (i, j)):
                        if j == 0:
                            if i == 0:
                                # transition from init stage to the first stage stage
                                x = self._residual_unit(x, 3, filter_size[i], stride[i])
                            else:
                                x = self._residual_unit(x, filter_size[i - 1], filter_size[i], stride[i])
                        else:
                            x = self._residual_unit(x, filter_size[i], filter_size[i], stride[i])
            #print(x)
            return x 

    def generator_conv(self, image, reuse=False):
        dim = 32
        with tf.variable_scope('compressor') as scope:
            if reuse : 
                scope.reuse_variables()
            conv1 = ly.conv2d(image,dim*1, kernel_size=3, stride=1, padding='SAME',
                              activation_fn=tf.nn.leaky_relu,
                              weights_initializer=tf.random_normal_initializer(0, 0.02))
            conv1 = self.bo_batch_norm(conv1, self.is_train)
            conv2 = ly.conv2d(conv1,dim*2, kernel_size=3, stride=1, padding='SAME', 
                              activation_fn=tf.nn.leaky_relu, 
                              weights_initializer=tf.random_normal_initializer(0, 0.02))
            conv2 = self.bo_batch_norm(conv2, self.is_train)
            conv3 = ly.conv2d(conv2,dim*4, kernel_size=3,stride=1, padding='SAME', 
                              activation_fn=tf.nn.leaky_relu, 
                              weights_initializer=tf.random_normal_initializer(0, 0.02))
            conv4 = self.bo_batch_norm(conv3, self.is_train)
            conv4 = ly.conv2d(conv3,dim*8, kernel_size=3, stride=1, padding='SAME',
                              activation_fn=tf.nn.leaky_relu, 
                              weights_initializer=tf.random_normal_initializer(0, 0.02))
            conv4 = self.bo_batch_norm(conv4, self.is_train)
            latent = ly.conv2d(conv4,3, kernel_size=3, stride=1, padding='SAME', 
                               activation_fn=tf.nn.leaky_relu, 
                               weights_initializer=tf.random_normal_initializer(0, 0.02))
            #latent = ly.fully_connected(tf.reshape(conv4, shape=[-1,7*7*dim*8]), self.arg.com, 
            #                            activation_fn=tf.nn.leaky_relu)
            print(latent)
        return latent 

    def adversary_lrr(self, latent, reuse=False):
        with tf.variable_scope('adversary_lrr') as scope:  
            if reuse: 
                scope.reuse_variables()
            recontruction = ly.fully_connected(latent, 32*32*3, activation_fn=None, 
                                               weights_initializer=tf.contrib.layers.xavier_initializer(), 
                                               biases_initializer = None)
        return tf.reshape(recontruction, shape=[-1, 32, 32, 3])


    def adversary_krr(self, kernel_map, reuse=False):
        with tf.variable_scope('adversary_krr') as scope:  
            if reuse: 
                scope.reuse_variables()
            recontruction = ly.fully_connected(kernel_map, 32*32*3, 
                                               activation_fn=None, 
                                               weights_initializer=tf.contrib.layers.xavier_initializer(), 
                                               biases_initializer = None)
        return tf.reshape(recontruction, shape=[-1, 32, 32, 3])

    def adversary_nn(self,latent,reuse=False):
        with tf.variable_scope('adversary_nn') as scope:
            if reuse:
                scope.reuse_variables()
            dim = 32
            latent = ly.flatten(latent)
            latent = ly.fully_connected(latent, 4*4*64, activation_fn=tf.nn.relu)
            latent = self.bo_batch_norm(latent, self.is_train)
            latent = tf.reshape(latent, shape=[-1, 4, 4, 64])
            upsample1 = ly.conv2d_transpose(latent, dim*4, kernel_size=3, stride=2, padding='SAME',
                                                activation_fn=tf.nn.relu, 
                                                weights_initializer=tf.random_normal_initializer(0, 0.02))
            #upsample1 = self.bo_batch_norm(upsample1, self.is_train)
            upsample2 = ly.conv2d_transpose(upsample1, dim*2, kernel_size=3, stride=2, padding='SAME',
                                                activation_fn=tf.nn.relu, 
                                                weights_initializer=tf.random_normal_initializer(0, 0.02))
            #upsample5 = ly.conv2d_transpose(upsample2, dim*1, kernel_size=3, stride=1, padding='SAME',activation_fn=tf.nn.relu, weights_initializer=tf.random_normal_initializer(0, 0.02))
            upsample6 = ly.conv2d_transpose(upsample2, 3, kernel_size=3, stride=2, padding='SAME',
                                                activation_fn=tf.nn.tanh,
                                                weights_initializer=tf.random_normal_initializer(0, 0.02))
        return upsample6 

    def RFF_map(self, input_tensor, seed, stddev, output_dim): 
        """
        Refer to the scikit learn package "RFF sampler" and tensorflow RFF mapping.
        """

        random_state = check_random_state(seed)
        gamma = stddev
        omega_matrix_shape = [3072, output_dim]
        bias_shape = [output_dim]
        """
        Tensorflow Version is elaborated below:

        np.random.seed(9)
        self._stddev = stddev
        omega_matrix_shape = [self.arg.dim*2, output_dim]
        bias_shape = [output_dim]

        omega_matrix = constant_op.constant(
            np.random.normal(
            scale=1.0 / self._stddev, size=omega_matrix_shape),
            dtype=dtypes.float32)

        bias = constant_op.constant(
            np.random.uniform(
            low=0.0, high=2 * np.pi, size=bias_shape),
            dtype=dtypes.float32)

        x_omega_plus_bias = math_ops.add(
            math_ops.matmul(input_tensor, omega_matrix), bias)
        """

        omega_matrix = constant_op.constant(np.sqrt(2 * gamma) *
           random_state.normal(size=omega_matrix_shape), dtype=dtypes.float32)

        bias = constant_op.constant(
            random_state.uniform(
            0.0, 2 * np.pi, size=bias_shape), dtype=dtypes.float32)

        x_omega_plus_bias = math_ops.add(
            math_ops.matmul(input_tensor, omega_matrix), bias)

        return math.sqrt(2.0 / output_dim) * math_ops.cos(x_omega_plus_bias)


    def build_model(self):
        # Input placeholdr
        self.image_p = tf.placeholder(tf.float32, shape=[None,32,32,3])
        self.label_p = tf.placeholder(tf.int64, shape=[None])
        self.is_train = tf.placeholder(tf.bool)
        self.learning_rate_p = tf.placeholder(tf.float32)
        self.dropout = tf.placeholder(tf.float32)
        self.one_hot = tf.one_hot(self.label_p, 10)

        # Privatizer 
        self.latent = self.residual_g(self.image_p)

        # Classifier 
        self.logit = self.wrs_16_2(self.latent)
        self.prob = tf.nn.softmax(self.logit)

        # Adversary
        self.latent = ly.flatten(self.latent)
        self.lrr_mu_p = tf.placeholder(tf.float32, shape=[3072])
        self.krr_mu_p = tf.placeholder(tf.float32, shape=[self.mapping_dim])
        self.t_mu_p = tf.placeholder(tf.float32, shape=[32*32*3])
        self.krr_weights = tf.placeholder(tf.float32, shape=[self.mapping_dim, 32*32*3])
        self.lrr_weights = tf.placeholder(tf.float32, shape=[3072, 32*32*3])
        self.lrr_mu = self.init_tensor([3072])
        self.krr_mu = self.init_tensor([self.mapping_dim])  
        self.t_mu = self.init_tensor([3072])

        # Center-adjusted code, refering from Kung's book. 
        # If it is needed, please remove the comment symbol.
        #self.latent_lrr = self.latent - self.lrr_mu
        self.kernel_map = self.RFF_map(self.latent, self.seed, self.gamma, self.mapping_dim)
        #self.kernel_map_deduct = self.kernel_map - self.krr_mu
        self.recon_nn = self.adversary_nn(self.latent)
        #self.recon_lrr = self.adversary_lrr(self.latent_lrr)
        self.recon_lrr = self.adversary_lrr(self.latent)
        #self.recon_krr = self.adversary_krr(self.kernel_map_deduct)
        self.recon_krr = self.adversary_krr(self.kernel_map)
        #self.recon_lrr = self.recon_lrr + tf.reshape(self.t_mu, [32,32,3])
        #self.recon_krr = self.recon_krr + tf.reshape(self.t_mu, [32,32,3])

        self.acc = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(self.prob,1), self.label_p), tf.float32))
        utility_loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.logit, labels=self.one_hot))
        self.loss_c = utility_loss 
        self.loss_r_nn = tf.losses.mean_squared_error(self.image_p, self.recon_nn) 
        self.loss_r_lrr = tf.losses.mean_squared_error(self.image_p, self.recon_lrr) 
        self.loss_r_krr = tf.losses.mean_squared_error(self.image_p, self.recon_krr) 
        self.loss_g_nn = utility_loss - self.loss_r_nn
        self.loss_g_lrr = 100*utility_loss - self.loss_r_lrr
        self.loss_g_krr = 100*utility_loss - self.loss_r_krr
        theta_fc = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='utility_classifier/logits')
        regularizer = 0
        l2_reg_loss = tf.add_n([tf.nn.l2_loss(var) for var in theta_fc])

        #self.loss = self.loss #+ 0.0001*l2_reg_loss
        self.theta_r_nn = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='adversary_nn')
        self.theta_r_lrr = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='adversary_lrr')
        self.theta_r_krr = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='adversary_krr')
        self.theta_g = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='compressor')
        self.theta_c = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, scope='utility_classifier')
        print('The numbers of parameters in variable_scope G are : {}'.format(self.count_number_trainable_params(self.theta_g)))
        print('The numbers of parameters in variable_scope R are : {}'.format(self.count_number_trainable_params(self.theta_c)))

        # ****************
        # Assign operation
        # ****************  
        self.assign_op = []
        assign_lrr = self.theta_r_lrr[0].assign(self.lrr_weights)
        self.assign_op.append(assign_lrr)

        assign_krr = self.theta_r_krr[0].assign(self.krr_weights)
        self.assign_op.append(assign_krr)

        assign_t_mu = self.t_mu.assign(self.t_mu_p)
        self.assign_op.append(assign_t_mu)

        assign_lrr_mu = self.lrr_mu.assign(self.lrr_mu_p)
        self.assign_op.append(assign_lrr_mu)

        assign_krr_mu = self.krr_mu.assign(self.krr_mu_p)
        self.assign_op.append(assign_krr_mu)

        ###****************************************************

        uti_update = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(uti_update):
            self.g_op_nn = tf.train.AdamOptimizer(self.lr)
            self.g_opt_nn = self.g_op_nn.minimize(self.loss_g_nn, var_list=self.theta_g)

            self.g_op_lrr = tf.train.AdamOptimizer(0.001)
            self.g_opt_lrr = self.g_op_lrr.minimize(self.loss_g_lrr, var_list=self.theta_g)

            self.g_op_krr = tf.train.AdamOptimizer(0.001)
            self.g_opt_krr = self.g_op_krr.minimize(self.loss_g_krr, var_list=self.theta_g)

            self.c_op = tf.train.MomentumOptimizer(self.learning_rate_p , 0.9, use_nesterov=True)
            self.c_opt = self.c_op.minimize(self.loss_c,var_list=self.theta_c)

            self.r_op = tf.train.MomentumOptimizer(self.learning_rate_p, 0.9, use_nesterov=True)
            self.r_opt = self.r_op.minimize(self.loss_r_nn, var_list=self.theta_r_nn)
        
        self.sess = tf.Session()
        self.sess.run(tf.global_variables_initializer())
        self.saver = tf.train.Saver()
    
    # We don't use the augumentation mechanism in our implementation, thus, these three
    # functions are no longer used.
    def batch_random_rotate_image(self, image):
        angle = np.random.uniform(low=-5.0, high=5.0)
        a = []
        for i in image:
            a.append(imrotate(i, angle, 'bicubic'))
        for i in range(len(a)):
            #a[i] = a[i]/255
            a[i] = (a[i]/127.5)-1
            #a[i] -= cifar_mean
            #a[i] /= cifar_std
        return a

    def batch_mirror_image(self,image):
        a = []
        for i in image :
            a.append(np.flipud(i))
        return a

    def batch_crop_image(self,image):
        a = [] 
        ind = [1,2]
        aug = random.sample(ind,1)
        if aug ==2 : 
            image = self.batch_mirror_image(image)
        else : 
            image = image 
        for i in image : 
            image_pad = np.pad(i,((4,4),(4,4),(0,0)),mode='constant')
            crop_x1 = random.randint(0,8)
            crop_x2 = crop_x1 + 32
            crop_y1 = random.randint(0,8)
            crop_y2 = crop_y1 + 32
            image_crop = image_pad[crop_x1:crop_x2,crop_y1:crop_y2]
            a.append(image_crop)
        return a
    # End here.

    def next_batch(self, data, label, shuffle=False, batch_size=256):
        data_size = len(data)
        iteration = data_size // batch_size
        data_rest_num = data_size - iteration * batch_size
        if shuffle:
            data_zip = list(zip(data, label))
            random.shuffle(data_zip)
            data, label = zip(*data_zip)
        for i in range(0, data_size, batch_size):
            if i ==  (iteration *batch_size) : 
                yield np.array(data[i:]), np.array(label[i:])
            else : 
                yield np.array(data[i: i+batch_size]), np.array(label[i: i+batch_size])

 
    def compute_acc(self, data, label):
        acc_list = []
        for batch_x, batch_y in self.next_batch(data, label, shuffle=False, batch_size=self.arg.batch_size):
            b = batch_x.shape[0]
            no = np.random.normal(size=(b, 32, 32, 3))
            feed_dict = {}
            feed_dict[self.image_p] = batch_x.reshape(b, 32, 32, 3)
            feed_dict[self.label_p] = k
            feed_dict[self.is_train] = False
            feed_dict[self.dropout] = 1.0
            pred = self.sess.run(self.prob, feed_dict=feed_dict)
            acc_list.append(pred)
        preds = np.concatenate((acc_list), axis=0)
        data_size = len(te_data)
        preds = preds[0:data_size]   
        ac = accuracy_score(np.argmax(preds, axis=1), label)
        return ac

    def cutout(self,img,n_holes,length):
        ### Never use this function !!!
        h = img.shape[0]
        w = img.shape[1]
        mask = np.ones((h, w), np.float32)
        for n in range(n_holes):

            y = np.random.randint(h)
            x = np.random.randint(w)

            y1 = np.clip(y - length // 2, 0, h)
            y2 = np.clip(y + length // 2, 0, h)
            x1 = np.clip(x - length // 2, 0, w)
            x2 = np.clip(x + length // 2, 0, w)

            mask[y1: y2, x1: x2] = 0.

        #mask = torch.from_numpy(mask)
        #mask = mask.expand_as(img)
        #mask = mask.reshape(32,32,1)
        for i in range(3):
            img[:,:,i] = img[:,:,i] *mask
        #img = img * mask
        return img

    def compute_reco_mse(self, val_data, val_label):
        ##### after assign all the weights !!!!! 
        error_nn = []
        error_lrr = []
        error_krr = []
        ### change to next batch function 
        for batch_x, batch_y in self.next_batch(val_data, val_label, shuffle=False, self.batch_size):
            b = batch_x.shape[0]
            no = np.random.laplace(size=(b, 32, 32, 3))   
            feed_dict = {}
            feed_dict[self.image_p] = batch_x.reshape(b, 32, 32, 3)
            feed_dict[self.is_train] = False
            up_nn = self.sess.run(self.recon_nn, feed_dict=feed_dict)
            up_lrr = self.sess.run(self.recon_lrr, feed_dict=feed_dict)
            up_krr = self.sess.run(self.recon_krr, feed_dict=feed_dict)
            for k in range(len(up_nn)):
                error_nn.append(mean_squared_error(i[k].flatten(), up_nn[k].flatten())) 
                error_lrr.append(mean_squared_error(i[k].flatten(), up_lrr[k].flatten())) 
                error_krr.append(mean_squared_error(i[k].flatten(), up_krr[k].flatten())) 

        # If u want to save the reconstruction images:
        #imsave('original.png', self.plot(i[0]))
        #imsave('nn_reco.png', self.plot(up_nn[0]))
        #imsave('lrr_reco.png', self.plot(up_lrr[0]))
        #imsave('krr_reco.png', self.plot(up_krr[0]))
        return np.mean(error_nn), np.mean(error_lrr), np.mean(error_krr)

    def KRR_close_form(self, emb_matrix, train_matrix, train_mu):
        # Use the random fourier transform to approximate the RBF kernel 
        # Note that the training data is too large so that we use the intrinsic space mapping 
        # And use the tensorflow conrtrib package to get the RFF mapping rather than hand crafting
        # More information refers to https://github.com/hichamjanati/srf  
        rau = 0.00001
        mu = np.mean(emb_matrix, axis=0)
        #emb_matrix = emb_matrix - mu
        emb_matrix = emb_matrix.T 
        s = np.dot(emb_matrix, emb_matrix.T)
        a,b = s.shape
        identity = np.identity(a)
        s_inv = np.linalg.inv(s + rau * np.identity(a))
        #train_norm = train_matrix - train_mu
        weights = np.dot(np.dot(s_inv,emb_matrix), train_matrix)
        print('Shape of KRR weights: {}'.format(weights.shape))
        return weights, mu 


    def LRR_close_form(self, emb_matrix, train_matrix, train_mu):

        mu = np.mean(emb_matrix, axis=0)
        #emb_matrix = emb_matrix - mu
        emb_matrix = emb_matrix.T
        rau = 0.00001
        s = np.dot(emb_matrix, emb_matrix.T)
        h,w = s.shape
        s_inv = np.linalg.inv(s+rau*np.identity(h))
        #train_norm = train_matrix - train_mu
        weights = np.dot(np.dot(s_inv, emb_matrix), train_matrix)
        print('Shape of LRR weights: {}'.format(weights.shape))
        return weights, mu 


    def get_emb_matrix(self): 
        count = 0
        for batch_x, batch_y in self.next_batch(self.t_data, self.t_label, False, self.batch_size):
            b = batch_x.shape[0]
            penal = np.array([[0.5, 1] for i in range(b)])
            no = np.random.normal(size=(b, 32, 32, 3))
            feed_dict = []
            feed_dict[self.image_p] = batch_x.reshape(b, 32, 32, 3)
            feed_dict[self.dropout] = 1.0
            feed_dict[self.is_train] = False
            compressing_representation, kernel_map = self.sess.run([self.latent, self.kernel_map], feed_dict=feed_dict)
            if count == 0 : 
                emb_matrix_lrr = compressing_representation_concat
                emb_matrix_krr = kernel_map
                count+=1 
            else : 
                emb_matrix_lrr = np.concatenate((emb_matrix_lrr, compressing_representation_concat), axis=0)
                emb_matrix_krr = np.concatenate((emb_matrix_krr, kernel_map), axis=0)
                count+=1 
        print('Successfully get embedding matrix')   
        return emb_matrix_lrr, emb_matrix_krr


    def get_train_matrix(self): 
        temp = []
        for i in self.t_data:
            temp.append(i.flatten().reshape(1,-1)) 
        train_matrix = np.concatenate(temp, axis=0)
        print('Successfully get flatted train matrix !!!!')   
        return train_matrix

    def assign(self, train_matrix, train_mu, epo):

        feed_dict_assign = {}
        emb_matrix_lrr, emb_matrix_krr = self.get_emb_matrix()
        error_list = []
        update_choice = [self.g_opt_nn, self.g_opt_lrr, self.g_opt_krr]
        assign_op = []
        lrr_weights, lrr_mu = self.LRR_close_form(emb_matrix_lrr, train_matrix, train_mu)
        feed_dict_assign[self.lrr_mu_p] = lrr_mu
        feed_dict_assign[self.lrr_weights] = lrr_weights
        krr_weights, krr_mu = self.KRR_close_form(emb_matrix_krr, train_matrix, train_mu)
        feed_dict_assign[self.krr_mu_p] = krr_mu
        feed_dict_assign[self.krr_weights] = krr_weights
        feed_dict_assign[self.t_mu_p] = train_mu
        self.sess.run(self.assign_op, feed_dict = feed_dict_assign)

        error_nn, error_lrr, error_krr = self.compute_reco_mse(self.v_data, self.v_label)
        error_list.append(error_nn) 
        error_list.append(error_lrr)
        error_list.append(error_krr)
        print('Average MSE among all testing images is {}, {}, {}.(nn,lrr,krr)'.format(error_nn, error_lrr, error_krr))
        optimize_g = update_choice[np.argmin(error_list)]
        return optimize_g, feed_dict_assign

    #### this training process may have some problems, see updata cosine learning rate and we do not need drop out ? 
    def train(self):
        loss_trace = []
        epochs = 160
        init_lr = 0.01
        cur_lr = init_lr
        is_best = 0
        train_matrix = self.get_train_matrix()
        train_mu = np.mean(train_matrix, axis=0)
        ### original inner loops for citers is 5 !!!! 
        ### have tried loops 15 ...
        for epo in range(self.arg.epoch) : 
            train_data = []
            train_label = [] 
            start_epo = time.time()
            for batch_x, batch_y in self.next_batch(self.t_data, self.t_label, True, self.args.batch):
                train_data.append(batch_x)
                train_label.append(batch_y)
                feed_dict = {}
                b = batch_x.shape[0]
                no = np.random.normal(size=(b, 32, 32, 3))
                feed_dict[self.image_p] = batch_x.reshape(-1, 32, 32, 3)
                feed_dict[self.label_p] = batch_y
                feed_dict[self.is_train] = True
                feed_dict[self.dropout] = 0.4
                feed_dict[self.learning_rate_p] = cur_lr
                if self.arg.cut_out :
                    l = []
                    for qq in i : 
                        l.append(self.cutout(qq, 1, 20))
                    feed_dict[self.image_p] = np.array(l).reshape(-1, 32, 32, 3)
                # ***********************************
                # Update Reconstructor and Classifier
                # ***********************************
                for _ in range(self.arg.citer):
                    _ = self.sess.run(self.r_opt, feed_dict = feed_dict)
                c_loss, _ = self.sess.run([self.loss_c, self.c_opt], feed_dict = feed_dict)
            

            optimize_g, feed_dict = self.assign(train_matrix, train_mu, epo)
            start_g = time.time()
            for ind in range(len(train_data)):
                feed_dict[self.image_p] = train_data[ind]
                feed_dict[self.label_p] = train_label[ind]
                feed_dict[self.is_train] = True 
                feed_dict[self.dropout] = 0.4
                feed_dict[self.learning_rate_p] = cur_lr
                # *****************
                # Update Privatizer
                # ***************** 
                _ = self.sess.run(optimize_g,feed_dict = feed_dict)
            end = time.time()
            self.save_g()
            print("Training for privatizer costs about {}.".format(end-start_g))
            if epo < 80 :
                cur_lr = 0.01

            elif epo > 80 and epo < 120 : 
                cur_lr = 0.0001
            else : 
                cur_lr = 0.00001
            acc_testing = self.compute_acc(self.te_data, self.te_label)#, is_train=True)
            acc_validation = self.compute_acc(self.v_data, self.v_label)
            print('Epoch [{}/{}], cost {} sec, validation acc {}'.format(epo+1, self.arg.epoch, end-start_epo, 
                                                                                         acc_validation))
            print("Validation accuracy: {}, testing accuracy: {}.".format(ac_acc, at_acc))
            if acc_validation > is_best:
                is_best = acc_validation
                self.saver.save(self.sess, os.path.join(self.arg.model_dir, self.arg.name+"_ckpt_best"))
                self.save_g()
            if (epo+1) % 10 == 0:
                self.saver.save(self.sess, os.path.join(self.arg.model_dir, self.arg.name+"_ckpt_"+str(epo+1)))
                self.plot_10slot()      

    def save_g(self):
        temp = self.sess.run(self.theta_g)
        weight = []
        for i in range(len(temp)):
            weight.append(temp[i].flatten())
        np.save(os.path.join(self.arg.model_dir, self.arg.name+"_weights.npy"), weight)

    def load_g(self):
        temp = np.load(os.path.join(self.arg.model_dir, self.arg.name+"_weights.npy"))
        assign = []
        for i in range(len(self.theta_g)):
            if temp[i].shape[0] > 3 :
                assign.append(tf.assign(self.theta_g[i],temp[i].reshape(3,3,3,3)))
            else : 
                assign.append(tf.assign(self.theta_g[i],temp[i]))
        return assign

    def plot(self,x):
        x = x - np.min(x)
        x = x / np.max(x)
        x *= 255  
        x= x.astype(np.uint8)
        x = x.reshape(32, 32, 3)
        return x 

    def plot_10slot(self, name="Reconsturcted_images.png"):

        random_sample_img = np.array(self.te_data[:128])
        random_sample_label = np.array([i for i in range(128)])
        no = np.random.normal(size=(128, 32, 32, 3))
        compress_representations = self.sess.run(self.latent, feed_dict={
                                                                        self.image_p:random_sample_img.reshape(128, 175, 175,3), 
                                                                        self.label_p:random_sample_label, 
                                                                        self.noise_p:no, 
                                                                        self.keep_prob:1})
        reconstructions = self.sess.run(self.up, feed_dict={self.latent_no:compress_representations})

        plt.figure(figsize=(10, 2))
        n = 10
        for i in range(n):
            ax = plt.subplot(2, n, i + 1)
            plt.imshow(self.plot(self.te_data[i]))
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)

            # display reconstruction
            ax = plt.subplot(2, n, i + 1 + n)
            plt.imshow(self.plot(reconstructions[i]))
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
        plt.savefig(os.path.join(self.arg.model_dir, name))

    def _update_learning_rate_cosine(self, global_step, num_iterations):
        """
        update current learning rate, using Cosine function without restart(Loshchilov & Hutter, 2016).
        """
        global_step = min(global_step, num_iterations)
        decay_step = num_iterations
        alpha = 0
        cosine_decay = 0.5 * (1 + math.cos(math.pi * global_step / decay_step))
        decayed = (1 - alpha) * cosine_decay + alpha
        new_learning_rate = self.init_learning_rate * decayed
        self.op._lr = new_learning_rate
        #self.curr_learning_rate = new_learning_rate

    def test(self):
        #self.saver.restore(self.sess,'cpgan_log/model_141') #Our manuscript may use it!
        self.saver.restore(self.sess, os.path.join(self.arg.model_dir, self.arg.name+"_ckpt_best"))
        print('successfully restore')
        ac_acc = self.compute_acc(self.te_data, self.te_label)
        print('Testing utility accuracy is {}.'.format(ac_acc))

    def count_number_trainable_params(self, variable_scope):
        """
        Counts the number of trainable variables.
        """
        tot_nb_params = 0
        for trainable_variable in variable_scope:
            shape = trainable_variable.get_shape() # e.g [D,F] or [W,H,C]
            #print(shape)
            current_nb_params = self.get_nb_params_shape(shape)
            tot_nb_params = tot_nb_params + current_nb_params
        return tot_nb_params

    def get_nb_params_shape(self, shape):
        '''
        Computes the total number of params for a given shap.
        Works for any number of shapes etc [D,F] or [W,H,C] computes D*F and W*H*C.
        '''
        nb_params = 1
        for dim in shape:
            nb_params = nb_params*int(dim)
        return nb_params 



    # **********************************************
    # Below function is no longer used, since tuning the best kernel parameter for each epoch is too intractable, and it 
    # can not lead to better performance in our experiments. So we directly drop it! 
    # **********************************************
    def sklearn_sol(self, train_matrix, val_matrix, emb_matrix, emb_matrix_te, gamma ,mapping_dim, seed): 

        rbf_feature = RBFSampler(gamma=gamma, n_components=mapping_dim, random_state=seed)
        emb_matrix = rbf_feature.fit_transform(emb_matrix.reshape(-1,3072))
        #rau = self.arg.rau
        rau = 0.0001
        #emb_matrix = emb_matrix[:len(self.t_data)]
        mu = np.mean(emb_matrix, axis=0)
        emb_matrix_1 = emb_matrix #- mu
        #emb_matrix_1 = emb_matrix
        emb_matrix = emb_matrix_1.T 
        #print(np.mean(emb_matrix))
        s = np.dot(emb_matrix, emb_matrix.T)
        a,b = s.shape
        identity = np.identity(a)
        s_inv = np.linalg.inv(s + rau * np.identity(a))

        output_mu = np.mean(train_matrix, axis=0)
        output_norm = train_matrix# - output_mu
        weights = np.dot(np.dot(s_inv, emb_matrix), output_norm)
        #weights = np.dot(np.dot(s_inv, emb_matrix), self.t_label)
        pred = np.dot(emb_matrix_1, weights) # + output_mu       
        
        emb_matrix_te = rbf_feature.fit_transform(emb_matrix_te.reshape(-1, 3072))

        pred = np.dot(emb_matrix_te, weights) #+ output_mu        

        mse_trace = []
        for i in range(len(self.v_data)):
            mse_trace.append(mean_squared_error(val_matrix[i].flatten(), pred[i]))
        return np.mean(mse_trace)

    def tune(self, train_matrix, emb_matrix):
        ### This is for tune the parameter for each iteration (Not useful).
        count = 0
        for i, j in self.next_batch(self.v_data, self.v_label, self.batch_size):
            b = i.shape[0]
            penal = np.array([[0.5,1] for i in range(b)])
            no = np.random.normal(size=(128, 64, 64, 3))
            uu = self.sess.run(self.latent, feed_dict={self.image_p:i.reshape(b, 32, 32, 3), self.dropout:1, self.is_train:False})
            if count == 0 : 
                emb_matrix_te = uu
                #emb_matrix_krr = yy 
                #if compute: 
                val_matrix = i.reshape(-1, 32*32*3)
                count+=1 
            else : 
                emb_matrix_te = np.concatenate((emb_matrix_te, uu), axis=0)
                #emb_matrix_krr = np.concatenate((emb_matrix_krr, yy), axis=0)
                #if compute: 
                val_matrix = np.concatenate((val_matrix, i.reshape(-1, 32*32*3)), axis=0)
                count+=1 

        gamma_record = [] 
        seed_record = []
        dimension_record = [] 
        mse_record = []

        mse = self.sklearn_sol(train_matrix, val_matrix, emb_matrix, emb_matrix_te, self.gamma, self.mapping_dim, self.seed)
        print("First MSE that sklean solution caused: {}.".format(mse))

        gamma_record.append(self.gamma)
        seed_record.append(self.seed)
        dimension_record.append(self.mapping_dim)
        mse_record.append(mse)

        gamma_choices = list(np.arange(0, 100, 0.000001))
        seed_choices = [i for i in range(100)]
        dimension_choices = [(i+500) for i in range(0,8500,500)]

        for i in range(5):

            self.gamma = random.sample(gamma_choices, 1)[0]
            self.seed = random.sample(seed_choices, 1)[0]
            self.mapping_dim = random.sample(dimension_choices, 1)[0]

            gamma_record.append(self.gamma)
            seed_record.append(self.seed)
            dimension_record.append(self.mapping_dim)
            mse = self.sklearn_sol(train_matrix, val_matrix, emb_matrix, emb_matrix_te, self.gamma, self.mapping_dim, self.seed)
            mse_record.append(mse)


            print("Mse = {}. Parameters: is gamma, seed, mapping_dim:{}, {}, {}.".
                format(mse, self.gamma, self.seed, self.mapping_dim))

        index = np.argmin(mse_record)

        gamma = gamma_record[index]
        seed = seed_record[index]
        mapping_dim = dimension_record[index]

        return gamma, seed, mapping_dim











