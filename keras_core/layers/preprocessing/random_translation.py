from keras_core import backend
from keras_core.api_export import keras_core_export
from keras_core.layers.preprocessing.tf_data_layer import TFDataLayer
from keras_core.random.seed_generator import SeedGenerator


@keras_core_export("keras_core.layers.RandomTranslation")
class RandomTranslation(TFDataLayer):
    """A preprocessing layer which randomly translates images during training.

    This layer will apply random translations to each image during training,
    filling empty space according to `fill_mode`.

    Input pixel values can be of any range (e.g. `[0., 1.)` or `[0, 255]`) and
    of integer or floating point dtype. By default, the layer will output
    floats.

    Input shape:
        3D (unbatched) or 4D (batched) tensor with shape:
        `(..., height, width, channels)`, in `"channels_last"` format,
        or `(..., channels, height, width)`, in `"channels_first"` format.

    Output shape:
        3D (unbatched) or 4D (batched) tensor with shape:
        `(..., target_height, target_width, channels)`,
        or `(..., channels, target_height, target_width)`,
        in `"channels_first"` format.

    **Note:** This layer is safe to use inside a `tf.data` pipeline
    (independently of which backend you're using).

    Args:
        height_factor: a float represented as fraction of value, or a tuple of
            size 2 representing lower and upper bound for shifting vertically. A
            negative value means shifting image up, while a positive value means
            shifting image down. When represented as a single positive float,
            this value is used for both the upper and lower bound. For instance,
            `height_factor=(-0.2, 0.3)` results in an output shifted by a random
            amount in the range `[-20%, +30%]`. `height_factor=0.2` results in
            an output height shifted by a random amount in the range
            `[-20%, +20%]`.
        width_factor: a float represented as fraction of value, or a tuple of
            size 2 representing lower and upper bound for shifting horizontally.
            A negative value means shifting image left, while a positive value
            means shifting image right. When represented as a single positive
            float, this value is used for both the upper and lower bound. For
            instance, `width_factor=(-0.2, 0.3)` results in an output shifted
            left by 20%, and shifted right by 30%. `width_factor=0.2` results
            in an output height shifted left or right by 20%.
        fill_mode: Points outside the boundaries of the input are filled
            according to the given mode
            (one of `{"constant", "reflect", "wrap", "nearest"}`).
            - *reflect*: `(d c b a | a b c d | d c b a)` The input is extended
                by reflecting about the edge of the last pixel.
            - *constant*: `(k k k k | a b c d | k k k k)` The input is extended
                by filling all values beyond the edge with the same constant
                value k = 0.
            - *wrap*: `(a b c d | a b c d | a b c d)` The input is extended by
                wrapping around to the opposite edge.
            - *nearest*: `(a a a a | a b c d | d d d d)` The input is extended
                by the nearest pixel.
        interpolation: Interpolation mode. Supported values: `"nearest"`,
            `"bilinear"`.
        seed: Integer. Used to create a random seed.
        fill_value: a float represents the value to be filled outside the
            boundaries when `fill_mode="constant"`.
        data_format: string, either `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs. `"channels_last"`
            corresponds to inputs with shape `(batch, height, width, channels)`
            while `"channels_first"` corresponds to inputs with shape
            `(batch, channels, height, width)`. It defaults to the
            `image_data_format` value found in your Keras config file at
            `~/.keras/keras.json`. If you never set it, then it will be
            `"channels_last"`.
        **kwargs: Base layer keyword arguments, such as `name` and `dtype`.
    """

    _FACTOR_VALIDATION_ERROR = (
        "The `factor` argument should be a number (or a list of two numbers) "
        "in the range [-1.0, 1.0]. "
    )
    _SUPPORTED_FILL_MODE = ("reflect", "wrap", "constant", "nearest")
    _SUPPORTED_INTERPOLATION = ("nearest", "bilinear")

    def __init__(
        self,
        height_factor,
        width_factor,
        fill_mode="reflect",
        interpolation="bilinear",
        seed=None,
        fill_value=0.0,
        data_format=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.height_factor = height_factor
        self.height_lower, self.height_upper = self._set_factor(
            height_factor, "height_factor"
        )
        self.width_factor = width_factor
        self.width_lower, self.width_upper = self._set_factor(
            width_factor, "width_factor"
        )

        if fill_mode not in self._SUPPORTED_FILL_MODE:
            raise NotImplementedError(
                f"Unknown `fill_mode` {fill_mode}. Expected of one "
                f"{self._SUPPORTED_FILL_MODE}."
            )
        if interpolation not in self._SUPPORTED_INTERPOLATION:
            raise NotImplementedError(
                f"Unknown `interpolation` {interpolation}. Expected of one "
                f"{self._SUPPORTED_INTERPOLATION}."
            )

        self.fill_mode = fill_mode
        self.fill_value = fill_value
        self.interpolation = interpolation
        self.seed = seed
        self.generator = SeedGenerator(seed)
        self.data_format = backend.standardize_data_format(data_format)
        self.supports_jit = False

    def _set_factor(self, factor, factor_name):
        if isinstance(factor, (tuple, list)):
            if len(factor) != 2:
                raise ValueError(
                    self._FACTOR_VALIDATION_ERROR
                    + f"Received: {factor_name}={factor}"
                )
            self._check_factor_range(factor[0])
            self._check_factor_range(factor[1])
            lower, upper = sorted(factor)
        elif isinstance(factor, (int, float)):
            self._check_factor_range(factor)
            factor = abs(factor)
            lower, upper = [-factor, factor]
        else:
            raise ValueError(
                self._FACTOR_VALIDATION_ERROR
                + f"Received: {factor_name}={factor}"
            )
        return lower, upper

    def _check_factor_range(self, input_number):
        if input_number > 1.0 or input_number < -1.0:
            raise ValueError(
                self._FACTOR_VALIDATION_ERROR
                + f"Received: input_number={input_number}"
            )

    def call(self, inputs, training=True):
        inputs = self.backend.cast(inputs, self.compute_dtype)
        if training:
            return self._randomly_translate_inputs(inputs)
        else:
            return inputs

    def _randomly_translate_inputs(self, inputs):
        unbatched = len(inputs.shape) == 3
        if unbatched:
            inputs = self.backend.numpy.expand_dims(inputs, axis=0)

        batch_size = self.backend.shape(inputs)[0]
        if self.data_format == "channels_first":
            height = inputs.shape[-2]
            width = inputs.shape[-1]
        else:
            height = inputs.shape[-3]
            width = inputs.shape[-2]

        seed_generator = self._get_seed_generator(self.backend._backend)
        height_translate = self.backend.random.uniform(
            minval=self.height_lower,
            maxval=self.height_upper,
            shape=[batch_size, 1],
            seed=seed_generator,
        )
        height_translate = height_translate * height
        width_translate = self.backend.random.uniform(
            minval=self.width_lower,
            maxval=self.width_upper,
            shape=[batch_size, 1],
            seed=seed_generator,
        )
        width_translate = width_translate * width
        translations = self.backend.cast(
            self.backend.numpy.concatenate(
                [width_translate, height_translate], axis=1
            ),
            dtype="float32",
        )

        outputs = self.backend.image.affine_transform(
            inputs,
            transform=self._get_translation_matrix(translations),
            interpolation=self.interpolation,
            fill_mode=self.fill_mode,
            fill_value=self.fill_value,
            data_format=self.data_format,
        )

        if unbatched:
            outputs = self.backend.numpy.squeeze(outputs, axis=0)
        return outputs

    def _get_translation_matrix(self, translations):
        num_translations = self.backend.shape(translations)[0]
        # The translation matrix looks like:
        #     [[1 0 -dx]
        #      [0 1 -dy]
        #      [0 0 1]]
        # where the last entry is implicit.
        # translation matrices are always float32.
        return self.backend.numpy.concatenate(
            [
                self.backend.numpy.ones((num_translations, 1)),
                self.backend.numpy.zeros((num_translations, 1)),
                -translations[:, 0:1],
                self.backend.numpy.zeros((num_translations, 1)),
                self.backend.numpy.ones((num_translations, 1)),
                -translations[:, 1:],
                self.backend.numpy.zeros((num_translations, 2)),
            ],
            axis=1,
        )

    def compute_output_shape(self, input_shape):
        return input_shape

    def get_config(self):
        base_config = super().get_config()
        config = {
            "height_factor": self.height_factor,
            "width_factor": self.width_factor,
            "fill_mode": self.fill_mode,
            "interpolation": self.interpolation,
            "seed": self.seed,
            "fill_value": self.fill_value,
            "data_format": self.data_format,
        }
        return {**base_config, **config}
