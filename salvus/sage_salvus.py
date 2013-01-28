##################################################################################
#                                                                                #
# Extra code that the Salvus server makes available in the running Sage session. #
#                                                                                #
##################################################################################

import sys

salvus = None


import json
from uuid import uuid4
def uuid():
    return str(uuid4())

callbacks = {}

def register_callback(f):
    cb_uuid = uuid()
    callbacks[cb_uuid] = f   # todo -- should be a weak ref?
    return cb_uuid

def call(cb_uuid, value):
    salvus.obj(callbacks[cb_uuid](value))

def input_box0(cb):
    cb_uuid = register_callback(cb)
    salvus.coffeescript("interact.input_box(cell:cell, cb_uuid:'%s')"%cb_uuid)


########################

variables = {}

def register_variable(name, namespace, var_uuid=None):
    if var_uuid is None:
        var_uuid = uuid()
    variables[var_uuid] = (namespace, name)
    return var_uuid

def set_variable(var_uuid, value):
    namespace, name = variables[var_uuid]
    namespace[name] = value

def get_variable(var_uuid):
    namespace, name = variables[var_uuid]
    return namespace[name]

def input_box(variable, label='', namespace=None, from_str=None, default=None, container_id=None):
    if container_id is None:
        container_id = uuid()
        salvus.html("<span id='%s'></span>"%container_id)

    if namespace is None:
        namespace = salvus.namespace
    elif not isinstance(namespace, salvus.Namespace):
        raise TypeError, "namespace must be of type salvus.Namespace."

    if not isinstance(variable, str):
        i = id(variable)
        variable = None
        for x, y in namespace.iteritems():
            if id(y) == i:
                if variable is not None:
                    raise ValueError, "variable does not uniquely determine its name -- use a string instead"
                variable = x
        if variable is None:
            raise ValueError, "variable does not determine its name -- use a string instead"

    if from_str is not None:
        def do_from_str(x):
            try:
                return from_str(str(x))  # str is to convert it from unicode
            except Exception, mesg:
                return mesg
    else:
        def do_from_str(x): return str(x)

    def variable_changed_in_browser(val):
        namespace.set(variable, do_from_str(val), do_not_trigger=[variable_changed_in_python])
    cb_uuid = register_callback(variable_changed_in_browser)

    def variable_changed_in_python(val):
        salvus.execute_coffeescript("$('#%s').find('input').val('%s')"%(cb_uuid,val))
    namespace.on('change', variable, variable_changed_in_python)

    def variable_deleted_in_python():
        variable_changed_in_python('')

    namespace.on('del', variable, variable_deleted_in_python)

    if variable not in namespace:
        namespace[variable] = default
    else:
        variable_changed_in_browser(namespace[variable])

    # create the input box
    salvus.execute_coffeescript("$('#%s').append(interact.input_box(data))"%container_id,
              data = {'cb_uuid':cb_uuid, 'value':namespace[variable], 'label':label})

    return container_id


def checkbox(variable, label='', namespace=None, default=False, container_id=None):
    if container_id is None:
        container_id = uuid()
        salvus.html("<span id='%s'></span>"%container_id)

    default = bool(default)

    if namespace is None:
        namespace = salvus.namespace
    elif not isinstance(namespace, salvus.Namespace):
        raise TypeError, "namespace must be of type salvus.Namespace."
    if not isinstance(variable, str):
        i = id(variable)
        variable = None
        for x, y in namespace.iteritems():
            if id(y) == i:
                if variable is not None:
                    raise ValueError, "variable does not uniquely determine its name -- use a string instead"
                variable = x
        if variable is None:
            raise ValueError, "variable does not determine its name -- use a string instead"

    def variable_changed_in_browser(val):
        namespace.set(variable, bool(val), do_not_trigger=[variable_changed_in_python])
    cb_uuid = register_callback(variable_changed_in_browser)

    def variable_changed_in_python(val):
        salvus.execute_coffeescript("$('#%s').find('input').attr('checked', data)"%cb_uuid, data=bool(val))
    namespace.on('change', variable, variable_changed_in_python)

    def variable_deleted_in_python():
        variable_changed_in_python(False)

    namespace.on('del', variable, variable_deleted_in_python)

    if variable not in namespace:
        namespace[variable] = default
    else:
        variable_changed_in_browser(namespace[variable])

    # create the checkbox.
    salvus.execute_coffeescript("$('#%s').append(interact.checkbox(data))"%container_id,
              data = {'cb_uuid':cb_uuid, 'value':namespace[variable], 'label':label})

    return container_id


##########################################################################
# New function interact implementation -- doesn't use code from above!
##########################################################################
import inspect

interacts = {}

def jsonable(x):
    """
    Given any object x, make a JSON-able version of x, doing as best we can.
    For some objects, sage as Sage integers, this works well.  For other
    objects which make no sense in Javascript, we get a string.
    """
    import sage.all
    try:
        json.dumps(x)
        return x
    except:
        if isinstance(x, (sage.all.Integer)):
            return int(x)
        else:
            return str(x)

class InteractCell(object):
    def __init__(self, f, layout=None, width=None):
        """
        Given a function f, create an object that describes an interact
        for working with f interactively.
        """
        self._uuid = uuid()
        # Prevent garbage collection until client specifically requests it,
        # since we want to be able to store state.
        interacts[self._uuid] = self

        self._f = f
        self._layout = layout
        self._width = width if width is None else str(width)

        (args, varargs, varkw, defaults) = inspect.getargspec(f)
        if defaults is None:
            defaults = []

        n = len(args) - len(defaults)
        self._controls  = dict([(arg, interact_control(arg, defaults[i-n] if i >= n else None))
                           for i, arg in enumerate(args)])

        self._last_vals = {}
        for arg in args:
            self._last_vals[arg] = self._controls[arg].default()

        self._ordered_args = args
        self._args = set(args)

    def jsonable(self):
        """
        Return a JSON-able description of this interact, which the client
        can use for laying out controls.
        """
        X = {'controls':[self._controls[arg].jsonable() for arg in self._ordered_args], 'id':self._uuid}
        if self._width is not None:
            X['width'] = self._width
        if self._layout is not None:
            X['layout'] = self._layout
        return X

    def __call__(self, vals):
        """
        Call self._f with inputs specified by vals.  Any input variables not
        specified in vals will have the value they had last time.
        """
        self.triggers = [str(x) for x in vals.keys()]
        for k, v in vals.iteritems():
            x = self._controls[k](v)
            self._last_vals[k] =  x
        interact_exec_stack.append(self)
        try:
            self._f(**dict([(k,self._last_vals[k]) for k in self._args]))
        finally:
            interact_exec_stack.pop()

class _interact_layout:
    def __init__(self, layout, width):
        self._layout = layout
        self._width = width
    def __call__(self, f):
        return interact(f, self._layout, self._width)

class Interact(object):
    """
    Use interact to create interactive worksheet cells with sliders,
    text boxes, radio buttons, check boxes, color selectors, and more.

    Put ``@interact`` on the line before a function definition in a
    cell by itself, and choose appropriate defaults for the variable
    names to determine the types of controls (see tables below).  You
    may also put ``@interact(layout=...)`` to control the layout of
    controls.    Within the function, you may explicitly set the value
    of the control corresponding to a variable foo to bar by typing
    interact.foo = bar.

    Type "interact.controls.[tab]" to get access to all of the controls.

    INPUT:

    - `f` -- function
    - `layout` -- TODO
    - `width` -- number, or string such as '80%', '300px', '20em'.

    OUTPUT:

    - creates an interactive control.


    AUTOMATIC CONTROL RULES
    -----------------------

    There are also some defaults that allow you to make controls
    automatically without having to explicitly specify them.  E.g.,
    you can make ``x`` a continuous slider of values between ``u`` and
    ``v`` by just writing ``x=(u,v)`` in the argument list.

    - ``u`` - blank input_box
    - ``u=elt`` - input_box with ``default=element``, unless other rule below
    - ``u=(umin,umax)`` - continuous slider (really `100` steps)
    - ``u=(umin,umax,du)`` - slider with step size ``du``
    - ``u=list`` - buttons if ``len(list)`` at most `5`; otherwise, drop down
    - ``u=generator`` - a slider (up to `10000` steps)
    - ``u=bool`` - a checkbox
    - ``u=Color('blue')`` - a color selector; returns ``Color`` object
    - ``u=matrix`` - an ``input_grid`` with ``to_value`` set to
      ``matrix.parent()`` and default values given by the matrix
    - ``u=(default, v)`` - ``v`` anything as above, with given ``default`` value
    - ``u=(label, v)`` - ``v`` anything as above, with given ``label`` (a string)

    EXAMPLES:


    We illustrate features that are only in Salvus, not in the Sage
    cell server or Sage notebook.

    You can set the value of a control called foo to 100 using
    interact.foo=100. For example::

        @interact
        def f(n=20, twice=None):
            interact.twice = int(n)*2


    In this example, we create and delete multiple controls depending
    on properties of the input::

        @interact
        def f(n=20, **kwds):
            print kwds
            n = Integer(n)
            if n % 2 == 1:
                del interact.half
            else:
                interact.half = input_box(n/2, readonly=True)
            if n.is_prime():
                interact.is_prime = input_box('True', readonly=True)
            else:
                del interact.is_prime

    You can access the value of a control associated to a variable foo
    that you create using interact.foo, and check whether there is a
    control associated to a given variable name using hasattr::

        @interact
        def f():
            if not hasattr(interact, 'foo'):
                interact.foo = 'hello'
            else:
                print interact.foo

    An indecisive interact::

        @interact
        def f(n=selector(['yes', 'no'])):
            for i in range(5):
                interact.n = i%2
                sleep(.2)
    """
    def __call__(self, f=None, layout=None, width=None):
        if f is None:
            return _interact_layout(layout, width)
        else:
            salvus.interact(f, layout=layout, width=width)

    def __setattr__(self, arg, value):
        if arg in interact_exec_stack[-1]._controls and not isinstance(value, control):
            # setting value of existing control
            desc = {'var':arg, 'default':interact_exec_stack[-1]._controls[arg].convert_to_client(value)}
        else:
            # create a new control
            new_control = interact_control(arg, value)
            interact_exec_stack[-1]._controls[arg] = new_control
            desc = new_control.jsonable()
        salvus.javascript("cell._set_interact_var(obj)", obj=desc)

    def __delattr__(self, arg):
        try:
            del interact_exec_stack[-1]._controls[arg]
        except KeyError:
            pass
        salvus.javascript("cell._del_interact_var(obj)", obj=jsonable(arg))

    def __getattr__(self, arg):
        try:
            return interact_exec_stack[-1]._last_vals[arg]
        except Exception, err:
            print err
            raise AttributeError("no interact control corresponding to input variable '%s'"%arg)

    def triggers(self):
        """
        Return the variables whose change triggered evaluation of this
        interact.  [SALVUS only]

        For example::

            @interact
            def f(n=True, m=False, xyz=[1,2,3]):
                print n, m, interact.triggers()
        """
        return interact_exec_stack[-1].triggers

interact = Interact()
interact_exec_stack = []

class control:
    def __init__(self, control_type, opts, repr, convert_from_client=None, convert_to_client=jsonable):
        # The type of the control -- a string, used for CSS selectors, switches, etc.
        self._control_type = control_type
        # The options that define the control -- passed to client
        self._opts = dict(opts)
        # Used to print the control to a string.
        self._repr = repr
        # Callable that the control may use in converting from JSON
        self._convert_from_client = convert_from_client
        self._convert_to_client = convert_to_client
        self._last_value = self._opts['default']

    def convert_to_client(self, value):
        return self._convert_to_client(value)

    def __call__(self, obj):
        """
        Convert JSON-able object returned from client to describe
        value of this control.
        """
        if self._convert_from_client is not None:
            try:
                x = self._convert_from_client(obj)
            except Exception, err:
                sys.stderr.write("%s -- %s\n"%(err, self))
                sys.stderr.flush()
                x = self._last_value
        else:
            x = obj
        self._last_value = x
        return x

    def __repr__(self):
        return self._repr

    def label(self):
        """Return the label of this control."""
        return self._opts['label']

    def default(self):
        """Return default value of this control."""
        return self(self._opts['default'])

    def type(self):
        """Return type that values of this control are coerced to."""
        return self._opts['type']

    def jsonable(self):
        """Return JSON-able object the client browser uses to render the control."""
        X = {'control_type':self._control_type}
        for k, v in self._opts.iteritems():
            X[k] = jsonable(v)
        return X

import types

def automatic_control(default):
    from sage.matrix.all import is_Matrix
    from sage.all import Color
    label = None
    default_value = None

    for _ in range(2):
        if isinstance(default, tuple) and len(default) == 2 and isinstance(default[0], str):
            label, default = default
        if isinstance(default, tuple) and len(default) == 2 and isinstance(default[1], (tuple, list, types.GeneratorType)):
            default_value, default = default

    if isinstance(default, control):
        if label:
            default._opts['label'] = label
        return default
    elif isinstance(default, str):
        return input_box(default, label=label, type=str)
    elif isinstance(default, bool):
        return checkbox(default, label=label)
    elif isinstance(default, list):
        return selector(default, default=default_value, label=label, buttons=len(default) <= 5)
    elif isinstance(default, types.GeneratorType):
        return slider(list_of_first_n(default, 10000), default=default_value, label=label)
    elif isinstance(default, Color):
        return input_box(default, label=label, type=Color)
    elif isinstance(default, tuple):
        if len(default) == 2:
            return slider(default[0], default[1], default=default_value, label=label)
        elif len(default) == 3:
            return slider(default[0], default[1], default[2], default=default_value, label=label)
        else:
            return slider(list(default), default=default_value, label=label)
    elif is_Matrix(default):
        return input_grid(default.nrows(), default.ncols(), default=default.list(), to_value=default.parent())
    else:
        return input_box(default, label=label)

def interact_control(arg, value):
    if isinstance(value, control):
        if value._opts['label'] is None:
            value._opts['label'] = arg
        c = value
    else:
        c = automatic_control(value)
        if c._opts['label'] is None:
            c._opts['label'] = arg
    c._opts['var'] = arg
    return c

class ParseValue:
    def __init__(self, type):
        self._type = type
    def _eval(self, value):
        value = str(value)
        if value.isspace():
            return None
        if len(value.strip()) == 0:
            return None
        from sage.all import sage_eval
        return sage_eval(value, salvus.namespace)

    def __call__(self, value):
        from sage.all import Color
        if self._type is None:
            return self._eval(value)
        elif self._type is str:
            return str(value)
        elif self._type is Color:
            try:
                return Color(value)
            except ValueError:
                try:
                    return Color("#"+value)
                except ValueError:
                    raise TypeError("invalid color '%s'"%value)
        else:
            return self._type(self._eval(value))

def input_box(default=None, label=None, type=None, width=80, height=1, readonly=False):
    """
    An input box interactive control for use with the :func:`interact` command.
    """
    return control(
            control_type = 'input-box',
            opts         = locals(),
            repr         = "Input box labeled %r with default value %r"%(label, default),
            convert_from_client = ParseValue(type)
        )

def checkbox(default=True, label=None, readonly=False):
    """
    A checkbox interactive control for use with the :func:`interact` command.
    """
    return control(
            control_type = 'checkbox',
            opts         = locals(),
            repr         = "Checkbox labeled %r with default value %r"%(label, default)
        )

def color_selector(default=(0,0,1), label=None, readonly=False, widget='none', hide_box=False):
    """
    EXAMPLES::

        @interact
        def f(c=color_selector()):
            print c
    """
    return control(
            control_type = 'color-selector',
            opts         = locals(),
            repr         = "Checkbox labeled %r with default value %r"%(label, default)
        )

def text_control(default='', label='', classes=None):
    """
    A read-only control that displays arbitrary HTML amongst the other
    interact controls.  This is very powerful, since it can display
    any HTML.

    INPUT::

    - ``default`` -- actual HTML to display
    - ``label`` -- defaults to '', since usually you do not want a label
    - ``classes`` -- space separated string of CSS classes

    EXAMPLES::

    We output the factorization of a number in a text_control::

        @interact
        def f(n=2013,  fact=text_control("")):
            interact.fact = factor(n)

    We use a CSS class to make the text_control look like a button:

        @interact
        def f(n=text_control("foo <b>bar</b>", classes='btn')):
            pass

    We animate a picture into view:
 
        @interact
        def f(size=[10,15,..,30], speed=[1,2,3,4]):
            for k in range(size):
                interact.g = text_control("<img src='http://sagemath.org/pix/sage_logo_new.png' width=%s>"%(20*k))
                sleep(speed/50.0)
    """
    return control(
            control_type = 'text',
            opts         = locals(),
            repr         = "Text %r"%(default)
        )

def button(default=None, label=None, classes=None, width=None, icon=None):
    """
    Create a button.  [SALVUS only]

    You can tell that pressing this button triggered the interact
    evaluation because interact.triggers() will include the variable
    name tied to the button.

    INPUT:

    - ``default`` -- value variable is set to
    - ``label`` -- string (default: '')
    - ``classes`` -- string if None; if given, space separated
      list of CSS classes. e.g., Bootstrap CSS classes such as:
              btn-primary, btn-info, btn-success, btn-warning, btn-danger,
              btn-link, btn-large, btn-small, btn-mini.
      See http://twitter.github.com/bootstrap/base-css.html#buttons
      If button_classes a single string, that class is applied to all buttons.
    - ``width`` - an integer or string (default: None); if given,
      all buttons are this width.  If an integer, the default units
      are 'ex'.  A string that specifies any valid HTML units (e.g., '100px', '3em')
      is also allowed [SALVUS only].
    - ``icon`` -- None or string name of any icon listed at the font
      awesome website (http://fortawesome.github.com/Font-Awesome/), e.g., 'icon-repeat'

    EXAMPLES::

        @interact
        def f(hi=button('Hello', label='', classes="btn-primary btn-large"),
              by=button("By")):
            if 'hi' in interact.triggers():
                print "Hello to you, good sir."
            if 'by' in interact.triggers():
                print "See you."

    Some buttons with icons::

        @interact
        def f(n=button('repeat', icon='icon-repeat'),
              m=button('see?', icon="icon-eye-open", classes="btn-large")):
            print interact.triggers()
    """
    return control(
            control_type = "button",
            opts         = locals(),
            repr         = "Button",
            convert_from_client = lambda x : default,
            convert_to_client   = lambda x : str(x)
    )

def selector(values, label=None, default=None,
             nrows=None, ncols=None, width=None, buttons=False,
             button_classes=None):
    """
        A drop down menu or a button bar for use in conjunction with
        the :func:`interact` command.  We use the same command to
        create either a drop down menu or selector bar of buttons,
        since conceptually the two controls do exactly the same thing
        - they only look different.  If either ``nrows`` or ``ncols``
        is given, then you get a buttons instead of a drop down menu.

        INPUT:

        - ``values`` - either (1) a list [val0, val1, val2, ...] or (2)
          a list of pairs [(val0, lbl0), (val1,lbl1), ...] in which case
          all labels must be given -- use None to auto-compute a given label.
        - ``label`` - a string (default: None); if given, this label
          is placed to the left of the entire button group
        - ``default`` - an object (default: first); default value in values list
        - ``nrows`` - an integer (default: None); if given determines
          the number of rows of buttons; if given, buttons=True
        - ``ncols`` - an integer (default: None); if given determines
          the number of columns of buttons; if given, buttons=True
        - ``width`` - an integer or string (default: None); if given,
          all buttons are this width.  If an integer, the default units
          are 'ex'.  A string that specifies any valid HTML units (e.g., '100px', '3em')
          is also allowed [SALVUS only].
        - ``buttons`` - a bool (default: False, except as noted
          above); if True, use buttons
        - ``button_classes`` - [SALVUS only] None, a string, or list of strings
          of the of same length as values, whose entries are a whitespace-separated
          string of CSS classes, e.g., Bootstrap CSS classes such as:
              btn-primary, btn-info, btn-success, btn-warning, btn-danger,
              btn-link, btn-large, btn-small, btn-mini.
          See http://twitter.github.com/bootstrap/base-css.html#buttons
          If button_classes a single string, that class is applied to all buttons.
    """
    if (len(values) > 0 and isinstance(values[0], tuple) and len(values[0]) == 2):
        vals = [z[0] for z in values]
        lbls = [str(z[1]) if z[1] is not None else None for z in values]
    else:
        vals = values
        lbls = [None] * len(vals)

    for i in range(len(vals)):
        if lbls[i] is None:
            v = vals[i]
            lbls[i] = v if isinstance(v, str) else str(v)

    if default is None:
        default = 0
    else:
        try:
            default = vals.index(default)
        except IndexError:
            default = 0

    opts = dict(locals())
    for k in ['vals', 'values', 'i', 'v', 'z']:
        if k in opts:
            del opts[k]  # these could have a big jsonable repr

    opts['lbls'] = lbls
    return control(
            control_type        = 'selector',
            opts                = opts,
            repr                = "Selector labeled %r with values %s"%(label, values),
            convert_from_client = lambda n : vals[int(n)],
            convert_to_client   = lambda x : vals.index(x)
        )

interact_functions = {}
interact_controls = ['button', 'checkbox', 'color_selector', 'input_box', 'selector', 'text_control']

for f in ['interact'] + interact_controls:
    interact_functions[f] = globals()[f]

# A little magic so that "interact.controls.[tab]" shows all the controls.
class Controls:
    pass
Interact.controls = Controls()
for f in interact_controls:
    interact.controls.__dict__[f] = interact_functions[f]


