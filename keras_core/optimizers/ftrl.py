from keras_core import initializers
from keras_core import ops
from keras_core.api_export import keras_core_export
from keras_core.optimizers import optimizer


@keras_core_export(["keras_core.optimizers.Ftrl"])
class Ftrl(optimizer.Optimizer):
    r"""Optimizer that implements the FTRL algorithm.

    "Follow The Regularized Leader" (FTRL) is an optimization algorithm
    developed at Google for click-through rate prediction in the early 2010s. It
    is most suitable for shallow models with large and sparse feature spaces.
    The algorithm is described by
    [McMahan et al., 2013](https://research.google.com/pubs/archive/41159.pdf).
    The Keras version has support for both online L2 regularization
    (the L2 regularization described in the paper
    above) and shrinkage-type L2 regularization
    (which is the addition of an L2 penalty to the loss function).

    Initialization:

    ```python
    n = 0
    sigma = 0
    z = 0
    ```

    Update rule for one variable `w`:

    ```python
    prev_n = n
    n = n + g ** 2
    sigma = (n ** -lr_power - prev_n ** -lr_power) / lr
    z = z + g - sigma * w
    if abs(z) < lambda_1:
      w = 0
    else:
      w = (sgn(z) * lambda_1 - z) / ((beta + sqrt(n)) / alpha + lambda_2)
    ```

    Notation:

    - `lr` is the learning rate
    - `g` is the gradient for the variable
    - `lambda_1` is the L1 regularization strength
    - `lambda_2` is the L2 regularization strength
    - `lr_power` is the power to scale n.

    Check the documentation for the `l2_shrinkage_regularization_strength`
    parameter for more details when shrinkage is enabled, in which case gradient
    is replaced with a gradient with shrinkage.

    Args:
        learning_rate: A float, a
            `keras_core.optimizers.schedules.LearningRateSchedule` instance, or
            a callable that takes no arguments and returns the actual value to
            use. The learning rate. Defaults to 0.001.
        learning_rate_power: A float value, must be less or equal to zero.
            Controls how the learning rate decreases during training. Use zero
            for a fixed learning rate.
        initial_accumulator_value: The starting value for accumulators. Only
            zero or positive values are allowed.
        l1_regularization_strength: A float value, must be greater than or equal
            to zero. Defaults to `0.0`.
        l2_regularization_strength: A float value, must be greater than or equal
            to zero. Defaults to `0.0`.
        l2_shrinkage_regularization_strength: A float value, must be greater
            than or equal to zero. This differs from L2 above in that the L2
            above is a stabilization penalty, whereas this L2 shrinkage is a
            magnitude penalty. When input is sparse shrinkage will only happen
            on the active weights.
        beta: A float value, representing the beta value from the paper.
            Defaults to 0.0.
        {{base_optimizer_keyword_args}}
    """

    def __init__(
        self,
        learning_rate=0.001,
        learning_rate_power=-0.5,
        initial_accumulator_value=0.1,
        l1_regularization_strength=0.0,
        l2_regularization_strength=0.0,
        l2_shrinkage_regularization_strength=0.0,
        beta=0.0,
        weight_decay=None,
        clipnorm=None,
        clipvalue=None,
        global_clipnorm=None,
        use_ema=False,
        ema_momentum=0.99,
        ema_overwrite_frequency=None,
        name="ftrl",
    ):
        super().__init__(
            learning_rate=learning_rate,
            name=name,
            weight_decay=weight_decay,
            clipnorm=clipnorm,
            clipvalue=clipvalue,
            global_clipnorm=global_clipnorm,
            use_ema=use_ema,
            ema_momentum=ema_momentum,
            ema_overwrite_frequency=ema_overwrite_frequency,
        )

        if initial_accumulator_value < 0.0:
            raise ValueError(
                "`initial_accumulator_value` needs to be positive or zero. "
                "Received: initial_accumulator_value="
                f"{initial_accumulator_value}."
            )
        if learning_rate_power > 0.0:
            raise ValueError(
                "`learning_rate_power` needs to be negative or zero. Received: "
                f"learning_rate_power={learning_rate_power}."
            )
        if l1_regularization_strength < 0.0:
            raise ValueError(
                "`l1_regularization_strength` needs to be positive or zero. "
                "Received: l1_regularization_strength="
                f"{l1_regularization_strength}."
            )
        if l2_regularization_strength < 0.0:
            raise ValueError(
                "`l2_regularization_strength` needs to be positive or zero. "
                "Received: l2_regularization_strength="
                f"{l2_regularization_strength}."
            )
        if l2_shrinkage_regularization_strength < 0.0:
            raise ValueError(
                "`l2_shrinkage_regularization_strength` needs to be positive "
                "or zero. Received: l2_shrinkage_regularization_strength"
                f"={l2_shrinkage_regularization_strength}."
            )

        self.learning_rate_power = learning_rate_power
        self.initial_accumulator_value = initial_accumulator_value
        self.l1_regularization_strength = l1_regularization_strength
        self.l2_regularization_strength = l2_regularization_strength
        self.l2_shrinkage_regularization_strength = (
            l2_shrinkage_regularization_strength
        )
        self.beta = beta

    def build(self, var_list):
        """Initialize optimizer variables.

        Args:
            var_list: list of model variables to build Ftrl variables on.
        """
        if self.built:
            return
        super().build(var_list)
        self._accumulators = []
        self._linears = []
        for var in var_list:
            self._accumulators.append(
                self.add_variable(
                    shape=var.shape,
                    dtype=var.dtype,
                    name="accumulator",
                    initializer=initializers.Constant(
                        self.initial_accumulator_value,
                    ),
                )
            )
            self._linears.append(
                self.add_variable_from_reference(
                    reference_variable=var, name="linear"
                )
            )

    def update_step(self, gradient, variable, learning_rate):
        """Update step given gradient and the associated model variable."""

        lr = ops.cast(learning_rate, variable.dtype)
        gradient = ops.cast(gradient, variable.dtype)

        accum = self._accumulators[self._get_variable_index(variable)]
        linear = self._linears[self._get_variable_index(variable)]

        lr_power = self.learning_rate_power
        l2_reg = self.l2_regularization_strength
        l2_reg = l2_reg + self.beta / (2.0 * lr)

        # Ftrl optimizer has the same implementation for sparse and dense
        # gradients update.
        grad_to_use = (
            gradient + 2 * self.l2_shrinkage_regularization_strength * variable
        )
        new_accum = accum + ops.power(gradient, 2)
        linear.assign(
            linear
            + grad_to_use
            - (ops.power(new_accum, -lr_power) - ops.power(accum, -lr_power))
            / lr
            * variable
        )
        quadratic = ops.power(new_accum, (-lr_power)) / lr + 2 * l2_reg
        linear_clipped = ops.clip(
            linear,
            -self.l1_regularization_strength,
            self.l1_regularization_strength,
        )
        variable.assign((linear_clipped - linear) / quadratic)
        accum.assign(new_accum)

    def get_config(self):
        config = super().get_config()

        config.update(
            {
                "learning_rate_power": self.learning_rate_power,
                "initial_accumulator_value": self.initial_accumulator_value,
                "l1_regularization_strength": self.l1_regularization_strength,
                "l2_regularization_strength": self.l2_regularization_strength,
                "l2_shrinkage_regularization_strength": self.l2_shrinkage_regularization_strength,  # noqa: E501
                "beta": self.beta,
            }
        )
        return config


Ftrl.__doc__ = Ftrl.__doc__.replace(
    "{{base_optimizer_keyword_args}}", optimizer.base_optimizer_keyword_args
)
