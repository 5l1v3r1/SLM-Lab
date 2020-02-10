# Module to quickly build neural networks with relatively simple architecture
import inspect
import numpy as np
import pydash as ps
import torch
import torch.nn as nn

# TODO rebuild dependencies too


def get_nn_name(uncased_name):
    '''Helper to get the proper name in PyTorch nn given a case-insensitive name'''
    for nn_name in nn.__dict__:
        if uncased_name.lower() == nn_name.lower():
            return nn_name
    raise ValueError(f'Name {uncased_name} not found in {nn.__dict__}')


def build_activation_layer(activation):
    '''Helper to build an activation function layer for net'''
    if activation is None:
        return None
    else:
        ActivationClass = getattr(nn, get_nn_name(activation))
        return ActivationClass()


def resolve_activation_layer(net_spec, is_last_layer):
    '''
    Help resolve the activation layer depending if it's the last layer
    if not the last layer:
        use net_spec['activation']
    if the last layer and:
        if net_spec['out_activation'] is specified, use it
        else use net_spec['activation']
    @param dict:net_spec Specifying 'activation' and optionally 'out_activation'
    @return Layer:Activation
    '''
    activation, out_activation = ps.at(net_spec, *['activation', 'out_activation'])
    if not is_last_layer:
        return build_activation_layer(activation)
    else:  # last layer
        if 'out_activation' in net_spec:  # specified explicitly
            return build_activation_layer(out_activation)
        else:
            return build_activation_layer(activation)


def get_init_weights(init_fn, activation=None):
    '''
    Helper to get the init_weights function given init_fn and activation to be applied as net.apply(init_weights)
    @param str:init_fn
    @param str:activation
    @returns function:init_weights
    '''
    def init_weights(module):
        if (not hasattr(module, 'weight')) or 'BatchNorm' in module.__class__.__name__:
            # skip if not a module with weight, or if it's a BatchNorm layer
            return

        # init weight accordingly
        weight_init_fn = getattr(nn.init, init_fn)
        init_fn_args = inspect.getfullargspec(weight_init_fn).args
        # PyTorch supports calculating gain for these functions: https://pytorch.org/docs/stable/nn.init.html
        gain_supported_fns = ['linear', 'conv1d', 'conv2d', 'conv3d', 'conv_transpose1d', 'conv_transpose2d', 'conv_transpose3d', 'sigmoid', 'tanh', 'relu', 'leaky_relu']
        if activation is None:
            weight_init_fn(module.weight)
        elif 'gain' in init_fn_args and activation in gain_supported_fns:
            weight_init_fn(module.weight, gain=nn.init.calculate_gain(activation))
        elif 'nonlinearity' in init_fn_args:
            weight_init_fn(module.weight, nonlinearity=activation)
        else:
            weight_init_fn(module.weight)
        # init bias
        if module.bias is not None:
            nn.init.normal_(module.bias)
    return init_weights


def check_net_spec(net_spec):
    # CHECK FOR KEYS
    pass


def build_mlp_model(net_spec):
    '''
    Build an MLP model given net_spec
    @param dict:net_spec With the following format/example:
    net_spec = {
        "type": "mlp",
        "in_shape": [4],  # input shape
        "out_shape": [2],  # optional: output shape if this is a full model
        "layers": [64, 64],  # hidden layers
        "batch_norm": True,  # optional: apply BatchNorm before activation
        "activation": "relu",  # activation function
        "out_activation": None,  # optional: specify to override 'activation' for the last layer, useful for output model
        "init_fn": "orthogonal_",  # weight initialization
    }
    '''
    check_net_spec(net_spec)
    in_shape, out_shape, layers, batch_norm, activation, out_activation, init_fn = ps.at(net_spec, *['in_shape', 'out_shape', 'layers', 'batch_norm', 'activation', 'out_activation', 'init_fn'])

    nn_layers = []
    # if out_shape is specified in net_spec (a full network), copy layers and append out_shape to iterate
    layers = layers + out_shape if out_shape else layers

    if len(layers) == 0:  # if empty, use Identity and below won't iterate
        nn_layers.append(nn.Identity())
        net_spec['_out_shape'] = in_shape  # set new attribute from builder

    in_size = ps.get(in_shape, 0)
    for idx, out_size in enumerate(layers):
        is_last_layer = (idx == (len(layers) - 1))
        nn_layers.append(nn.Linear(in_size, out_size))
        if batch_norm and not is_last_layer:
            nn_layers.append(nn.BatchNorm1d(out_size))
        nn_layers.append(resolve_activation_layer(net_spec, is_last_layer=is_last_layer))
        in_size = out_size  # update in_size
        net_spec['_out_shape'] = [out_size]  # set new attribute from builder
    nn_layers = ps.compact(nn_layers)  # remove None
    mlp_model = nn.Sequential(*nn_layers)

    if init_fn:  # initialize weights if specified
        init_weights = get_init_weights(init_fn, activation)
        mlp_model.apply(init_weights)
    return mlp_model


def get_conv_out_shape(conv_model, in_shape):
    '''Helper to calculate the output shape of a conv model with flattened last layer given an input shape'''
    x = torch.rand(in_shape).unsqueeze(dim=0)
    if isinstance(conv_model, list):  # if passed nn_layers, build tmp model
        conv_model = nn.Sequential(*ps.compact(conv_model))
    y = conv_model(x).squeeze(dim=0)
    out_shape = y.shape
    return list(out_shape)


def build_conv_model(net_spec):
    '''
    Build a Conv1d, Conv2d (vision), or Conv3d model given net_spec
    Conv params: layer = [in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1]
    Layer contains arguments to Conv except the in_channels, which is inferred. Feel free to provide layer with as many params, since they are applied with *layer
    @param dict:net_spec With the following format/example:
    net_spec = {
        "type": "conv2d",  # options: 'conv1d', 'conv2d', conv3d
        "in_shape": [3, 84, 84],  # channel, height, width
        "out_shape": [2],  # optional: output shape if this is a full model. This must go with "flatten_out": True.
        "layers": [
            [32, 8, 4, 0, 1],  # out_channels, kernel_size, stride, padding, dilation
            [64, 4, 2, 0, 1],
            [32, 3, 1, 0, 1]
        ],
        "flatten_out": False,  # optional: flatten the conv output layer
        "batch_norm": True,  # optional: apply BatchNorm before activation
        "activation": "relu",  # activation function
        "out_activation": None,  # optional: specify to override 'activation' for the last layer, useful for output model
        "init_fn": "orthogonal_",  # weight initialization
    }
    '''
    check_net_spec(net_spec)
    in_shape, out_shape, layers, flatten_out, batch_norm, activation, out_activation, init_fn = ps.at(net_spec, *['in_shape', 'out_shape', 'layers', 'flatten_out', 'batch_norm', 'activation', 'out_activation', 'init_fn'])
    if net_spec['type'] == 'conv1d':
        ConvClass, BNClass = nn.Conv1d, nn.BatchNorm1d
    elif net_spec['type'] == 'conv2d':
        ConvClass, BNClass = nn.Conv2d, nn.BatchNorm2d
    elif net_spec['type'] == 'conv3d':
        ConvClass, BNClass = nn.Conv3d, nn.BatchNorm3d
    else:
        raise ValueError(f"type: {net_spec['type']} is not supported")

    in_c = in_shape[0]  # PyTorch image input shape is (c,h,w)
    nn_layers = []
    layers = layers + out_shape if out_shape else layers
    for idx, layer in enumerate(layers):
        is_last_layer = (idx == (len(layers) - 1))
        if isinstance(layer, list):
            out_c = layer[0]
            nn_layers.append(ConvClass(in_c, *layer))
            if batch_norm:
                nn_layers.append(BNClass(out_c))
            nn_layers.append(resolve_activation_layer(net_spec, is_last_layer=is_last_layer))
            in_c = out_c  # update
            if is_last_layer and (not out_shape) and flatten_out:
                nn_layers.append(nn.Flatten())
        else:  # if specified net_spec['out_shape] for output
            assert is_last_layer and out_shape and flatten_out
            # flatten conv model and get conv_out_shape
            nn_layers.append(nn.Flatten())
            conv_out_shape = get_conv_out_shape(nn_layers, in_shape)
            assert len(conv_out_shape) == 1 and len(out_shape) == 1
            # add the mlp output layer if specified in net_spec
            nn_layers.append(nn.Linear(conv_out_shape[0], out_shape[0]))
            nn_layers.append(resolve_activation_layer(net_spec, is_last_layer=is_last_layer))
    nn_layers = ps.compact(nn_layers)  # remove None
    conv_model = nn.Sequential(*nn_layers)
    net_spec['_out_shape'] = get_conv_out_shape(conv_model, in_shape)

    if init_fn:  # initialize weights if specified
        init_weights = get_init_weights(init_fn, activation)
        conv_model.apply(init_weights)
    return conv_model


class Recurrent(nn.Module):
    def __init__(self, net_spec):
        '''
        Build a Recurrent model given net_spec
        @param dict:net_spec With the following format/example:
        net_spec = {
            "type": "rnn",  # options: 'rnn', 'lstm', 'gru'
            "in_shape": [4],  # the number of features in x
            "out_shape": [2],  # optional: output shape if this is a full model
            "layers": [64, 64],  # the hidden layers, must be the same for all layers
            "bidirectional": False,  # whether to make network bidirectional
            "out_activation": None,  # optional: specify the 'activation' for the last layer only if out_shape is specified
            "init_fn": "orthogonal_",  # weight initialization
        }
        '''
        nn.Module.__init__(self)
        check_net_spec(net_spec)
        in_shape, out_shape, layers, bidirectional, init_fn = ps.at(net_spec, *['in_shape', 'out_shape', 'layers', 'bidirectional', 'init_fn'])

        assert len(in_shape) == 1
        in_size = in_shape[0]
        assert len(ps.uniq(layers)) == 1, f'layers must specify the same number of hidden units for each layer, but got {layers}'
        hidden_size = layers[0]
        num_dir = 2 if bidirectional else 1
        self.recurrent_model = getattr(nn, get_nn_name(net_spec['type']))(
            input_size=in_size, hidden_size=hidden_size, num_layers=len(layers),
            batch_first=True, bidirectional=bidirectional)
        # y.shape = (batch, seq_len, num_dir * hidden_size)
        # out_shape is of y without batch and varying seq_len, i.e. y.shape[-1]
        net_spec['_out_shape'] = [num_dir * hidden_size]  # set new attribute from builder

        if init_fn:  # initialize weights if specified
            init_weights = get_init_weights(init_fn)
            self.recurrent_model.apply(init_weights)

        if out_shape:  # if out_shape is specified in net_spec
            assert len(out_shape) == 1
            recurrent_out_size = num_dir * hidden_size  # the shape is from last_h_n, sliced along num_dir and concat
            nn_layers = []
            nn_layers.append(nn.Linear(recurrent_out_size, out_shape[0]))
            nn_layers.append(resolve_activation_layer(net_spec, is_last_layer=True))
            nn_layers = ps.compact(nn_layers)  # remove None
            self.mlp_model = nn.Sequential(*nn_layers)
            if init_fn:  # initialize weights if specified
                init_weights = get_init_weights(init_fn)
                self.recurrent_model.apply(init_weights)
            # since y is now an mlp output, out_shape is just as specified
            net_spec['_out_shape'] = out_shape  # set new attribute from builder

        self.hidden_size = hidden_size
        self.num_layers = len(layers)
        self.num_dir = num_dir

    def get_mlp_h_n(self, h_n):
        '''Get the h_n from the last rnn layer as flattened input for mlp'''
        # h_n.shape = (num_layers * num_dir, batch, hidden_size)
        batch = h_n.shape[1]
        split_h_n = h_n.view(self.num_layers, self.num_dir, batch, self.hidden_size)  # split h_n
        # get the last layer, concat along num_dir, so the resultant shape is (batch, num_dir * hidden_size)
        last_h_n = split_h_n[-1]  # the last layer
        mlp_h_n = last_h_n.view(1, batch, -1).squeeze(dim=0)  # slice along num_dir and concat
        return mlp_h_n

    def forward(self, *args, **kwargs):
        '''The feedforward step. Input is batch_size x seq_len x in_shape'''
        # y.shape = (batch, seq_len, num_dir * hidden_size)
        # h_n.shape = (num_layers * num_dir, batch, hidden_size)
        y, h_out = self.recurrent_model(*args, **kwargs)
        if hasattr(self, 'mlp_model'):
            # resolve hidden output h_out accordingly
            if self.recurrent_model._get_name() == 'LSTM':
                (h_n, c_n) = h_out
            else:
                h_n = h_out
            mlp_x = self.get_mlp_h_n(h_n)
            y = self.mlp_model(mlp_x)
        return y, h_out


def build_recurrent_model(net_spec):
    '''Recurrent model builder method for API consistency'''
    return Recurrent(net_spec)


MODEL_BUILDERS = {
    'mlp': build_mlp_model,
    'conv1d': build_conv_model,
    'conv2d': build_conv_model,
    'conv3d': build_conv_model,
    'rnn': build_recurrent_model,
    'gru': build_recurrent_model,
    'lstm': build_recurrent_model,
}


def build_model(net_spec):
    model_type = net_spec['type']
    if model_type in MODEL_BUILDERS:
        builder = MODEL_BUILDERS[model_type]
        return builder(net_spec)
    else:
        raise ValueError(f'type {model_type} is not supported.')


class FiLM(nn.Module):
    '''
    Feature-wise Linear Modulation layer https://distill.pub/2018/feature-wise-transformations/
    Takes a feature tensor and affine-transforms it with a conditioner tensor:
    output = cond_scale * feature + cond_shift
    The conditioner is always a vector with length = number of features or channels (image), and the operation is element-wise on feature or channel-wide (image)
    '''

    def __init__(self, net_spec):
        '''
        @param dict:net_spec With {'heads': head_spec, 'body': body_spec}
        head_spec must be updated with '_out_shape' from heads construction. The keys of head_spec must match the keys specified in body_spec.join.{feat,cond}
        '''
        nn.Module.__init__(self)
        joiner_spec = ps.get(net_spec, 'body.joiner')
        self.feat_name, self.cond_name = ps.at(joiner_spec, 'feat', 'cond')
        head_spec = net_spec['heads']  # must have '_out_shape' specified from head models
        feat_size = ps.get(head_spec, f'{self.feat_name}._out_shape.0')
        cond_size = ps.get(head_spec, f'{self.cond_name}._out_shape.0')
        # for constructing film cond weights
        film_spec = joiner_spec['film']
        film_spec.update({
            'in_shape': [cond_size],
            'out_shape': [feat_size],
        })
        self.cond_scale = build_model(film_spec)
        self.cond_shift = build_model(film_spec)
        joiner_spec['_out_shape'] = film_spec['out_shape']

    def forward(self, x_dict):
        '''Affine transform for FiLM; x_dict must be a dict {feat: tensor, cond: tensor}'''
        feat, cond = x_dict[self.feat_name], x_dict[self.cond_name]
        cond_scale_x = self.cond_scale(cond)
        cond_shift_x = self.cond_shift(cond)
        # use view to ensure cond transform will broadcast consistently across entire feature/channel
        view_shape = list(cond_scale_x.shape) + [1] * (feat.dim() - cond.dim())
        y = cond_scale_x.view(*view_shape) * feat + cond_shift_x.view(*view_shape)
        return y


class Concat(nn.Module):
    '''Flatten all input tensors and concatenate them'''

    def __init__(self, net_spec):
        nn.Module.__init__(self)
        joiner_spec = ps.get(net_spec, 'body.joiner')
        joiner_spec['_out_shape'] = [np.sum([head_spec['_out_shape'] for head_spec in net_spec['heads'].values()]).item()]

    def forward(self, x_dict):
        return torch.cat([t.flatten(start_dim=1) for t in x_dict.values()], dim=-1)


JOINER_BUILDERS = {
    'film': FiLM,
    'concat': Concat,
}


def build_joiner(net_spec):
    joiner_type = ps.get(net_spec, 'body.joiner.type')
    if joiner_type in JOINER_BUILDERS:
        builder = JOINER_BUILDERS[joiner_type]
        return builder(net_spec)
    else:
        raise ValueError(f'type {joiner_type} is not supported.')


class Hydra(nn.Module):
    '''Construct a basic Hydra network with a joined body'''
    # TODO elaborate

    def __init__(self, net_spec):
        '''
        @param dict:net_spec With {'heads': head_spec, 'body': body_spec, 'tails': tail_spec}
        '''
        nn.Module.__init__(self)
        heads = nn.ModuleDict()
        for name, head_spec in net_spec['heads'].items():
            head_spec['in_shape'] = list(xs[name].shape)[1:]
            heads.add_module(name, build_model(head_spec))

        # build joiner to join head outputs into a vector before passing to body
        joiner = build_joiner(net_spec)
        body_spec = net_spec['body']
        body_spec['in_shape'] = ps.get(body_spec, 'joiner._out_shape')
        body = build_model(body_spec)

        tails = nn.ModuleDict()
        for name, tail_spec in net_spec['tails'].items():
            tail_spec['in_shape'] = body_spec['_out_shape']
            tails.add_module(name, build_model(tail_spec))

        self.heads = heads
        self.joiner = joiner
        self.body = body
        self.tails = tails

    def forward(self, x):
        head_y = {name: head(x[name]) for name, head in self.heads.items()}
        film_y = self.joiner(head_y)
        body_y = self.body(film_y)
        tail_y = {name: tail(body_y) for name, tail in self.tails.items()}
        return tail_y


# TODO new tests
# TODO transformer
# TODO generic and Hydra network builder
# test case: one network
# test case: hydra network
# TODO decouple in_shape from spec. use data to inject


net_spec = {
    "heads": {
        "image": {
            "type": "conv2d",
            "in_shape": [3, 20, 20],
            "layers": [
                [16, 4, 2, 0, 1],
                [16, 4, 1, 0, 1]
            ],
            "flatten_out": True,
            "batch_norm": True,
            "activation": "relu",
            "init_fn": "orthogonal_",
        },
        "gyro": {
            "type": "mlp",
            "in_shape": [4],
            "layers": [],
            "batch_norm": False,
            "activation": "relu",
            "init_fn": "orthogonal_",
        },
    },
    "body": {  # this is special since it contains a models op
        # TODO specify feat and cond
        # TODO connect to a body model too
        "joiner": {
            "type": "concat",  # or concat
            # "type": "film",  # or concat
            # "feat": "image",
            # "cond": "gyro",
            # # film layer spec
            # "film": {
            #     "type": "mlp",
            #     "layers": [],
            #     "activation": "relu",
            #     "init_fn": "orthogonal_",
            # }
            # TODO auto-infer from out_shape for net_spec, so constructor has to operate on the full net_spec and be stateful
        },
        "type": "mlp",
        # "in_shape": [4],
        "layers": [256, 256],
        "activation": "relu",
        "init_fn": "orthogonal_",
    },
    "tails": {
        "v": {
            "type": "mlp",
            # "in_shape": [4],
            "out_shape": [1],
            "layers": [],
            "out_activation": None,
            "init_fn": "orthogonal_",
        },
        "pi": {
            "type": "mlp",
            # "in_shape": [4],
            "out_shape": [4],
            "layers": [],
            "out_activation": None,
            "init_fn": "orthogonal_",
        }
    }
}

# NOTE entire spec only has one level with in_shape and out_shape. Everything in between is inferred


batch = 8
x = {head: torch.rand([batch] + head_spec['in_shape']) for head, head_spec in net_spec['heads'].items()}
hydra = Hydra(net_spec)
hydra
hydra(x)
