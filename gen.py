#!/usr/bin/env python3
#
# Copyright (C) 2020 Viktor Sjölind
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along with this program.
# If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later
#

import xml.etree.ElementTree as ET
import re
import math
import sys

def is_exec(res):
    return res.operations.upper() == "E"

range_regex = re.compile("^(?P<min>-?\d+\.?\d*)\.\.+(?P<max>-?\d+\.?\d*)")

class LWM2MResource():

    def __init__(self, res_node):
        self.id = int(res_node.get("ID"))
        self.name = res_node.find("./Name").text
        self.operations = res_node.find("./Operations").text
        self.singleton = res_node.find("./MultipleInstances").text == "Single"
        self.mandatory = res_node.find("./Mandatory").text == "Mandatory"
        self.type = res_node.find("./Type").text
        self.description = res_node.find("./Description").text

        if self.type == "Integer":
            range_str = res_node.find("./RangeEnumeration").text

            if range_str is not None:
                m = range_regex.match(range_str)
                min_val = int(m.group("min"))
                max_val = int(m.group("max"))

                self.signed = min_val < 0
                self.byte_size = int(math.ceil(math.log2(max_val) / 8.0) * 8)

                if self.signed:
                    self.byte_size *= 2

                assert self.byte_size <= 64

            else:
                self.signed = True
                self.byte_size = 32

        if not is_exec(self):
            assert len(self.type) > 0

class LWM2MObject():

    def __init__(self, obj_node):
        self.name      = obj_node.find("./Name").text
        self.desc1     = obj_node.find("./Description1").text
        self.id        = int(obj_node.find("./ObjectID").text)
        self.objurn    = obj_node.find("./ObjectURN").text
        self.version   = obj_node.find("./ObjectVersion").text
        self.singleton = obj_node.find("./MultipleInstances").text == "Single"
        self.mandatory = obj_node.find("./Mandatory").text == "Mandatory"

        self.resources = []

        for res_node in obj_node.findall("./Resources/Item"):
            if res_node is not None:
                self.resources.append(LWM2MResource(res_node))


def def_format(string):
    return string.upper().replace(" ", "_")


def name_format(string):
    return string.lower().replace(" ", "_")


def gen_obj_id_def(obj):
    return "LWM2M_OBJECT_{}_ID".format(def_format(obj.name))


def gen_max_id(obj):
    return "{}_MAX_ID".format(def_format(obj.name))


def gen_res_def_name(obj, res):
    return "{}_{}".format(def_format(obj.name), def_format(res.name))


def gen_res_id_name(obj, res):
    return "{}_ID".format(gen_res_def_name(obj, res))


def gen_res_max_name(obj, res):
    return "{}_MAX".format(gen_res_def_name(obj, res))


def gen_file_head(obj):
    yield "/*\n"
    yield " * This is a generated stub\n"
    yield " *\n"
    yield " * SPDX-License-Identifier: Apache-2.0\n"
    yield " */\n\n"
    yield "#define LOG_MODULE_NAME net_lwm2m_obj_{}\n".format(name_format(obj.name))
    yield "#define LOG_LEVEL CONFIG_LWM2M_LOG_LEVEL\n\n"
    yield "#include <logging/log.h>\n"
    yield "LOG_MODULE_REGISTER(LOG_MODULE_NAME);\n\n"
    yield "#include <string.h>\n"
    yield "#include <stdio.h>\n"
    yield "#include <init.h>\n\n"
    yield "#include \"lwm2m_object.h\"\n"
    yield "#include \"lwm2m_engine.h\"\n\n"


def gen_res_defs(obj):
    yield "// FIXME: This should probably be defined elsewhere\n"
    yield "#define {} {}\n\n".format(gen_obj_id_def(obj), obj.id)

    yield "/* {} resource IDs */\n".format(obj.name)
    for res in obj.resources:
        yield "#define {} {}\n".format(gen_res_id_name(obj, res), res.id)
    yield "#define {} {}\n".format(gen_max_id(obj), len(obj.resources))
    yield "\n"

    if not obj.singleton:
        conf_name = "CONFIG_LWM2M_{}_INSTANCE_COUNT".format(def_format(obj.name))
        yield "#ifdef {}\n".format(conf_name)
        yield "#define MAX_INSTANCE_COUNT {}\n".format(conf_name)
        yield "#else\n"
        yield "// FIXME: This default value is generated. Please evaluate if it is sane and remove this comment.\n"
        yield "#define MAX_INSTANCE_COUNT 1\n".format(conf_name)
        yield "#endif\n\n"

    for res in obj.resources:
        if not res.singleton:
            max_name = gen_res_max_name(obj, res)
            yield "#ifdef CONFIG_{}\n".format(max_name)
            yield "#define {0} CONFIG_{0}\n".format(max_name)
            yield "#else\n"
            yield "// FIXME: This default value is generated. Please evaluate if it is sane and remove this comment.\n"
            yield "#define {} 1\n".format(max_name)
            yield "#endif\n\n"


def gen_res_inst_count(obj):

    nr_exec = 0
    multi_resources = []
    for res in obj.resources:
        if is_exec(res):
            nr_exec += 1
        elif not res.singleton:
            multi_resources.append(res)

    yield "/*\n"
    yield " * Calculate resource instances as follows:\n"
    yield " * start with DEVICE_MAX_ID\n"
    yield " * subtract EXEC resources ({})\n".format(nr_exec)
    yield " * subtract MULTI resources because their counts include 0 resource ({})\n".format(len(multi_resources))
    for res in multi_resources:
        yield " * add {}\n".format(gen_res_max_name(obj, res))
    yield " */\n"

    yield "#define RESOURCE_INSTANCE_COUNT ({} - {} - {}".format(gen_max_id(obj), nr_exec, len(multi_resources))
    if len(multi_resources) > 0:
        for res in multi_resources:
            yield " \\\n                                 + {}".format(gen_res_max_name(obj, res))
    yield ")\n"


def gen_data_struct_var_name(obj):
    return "{}_data".format(name_format(obj.name))

def gen_data_struct_type(obj):
    return "struct {}_t".format(gen_data_struct_var_name(obj))

def gen_data_struct(obj):

    yield "{} {{\n".format(gen_data_struct_type(obj))
    for res in obj.resources:
        if is_exec(res):
            continue

        typ_suffix = ""
        data_len = 64
        if res.type == "String":
            typ = "char"
            typ_suffix = "[{}]".format(data_len)

        elif res.type == "Integer":
            if res.signed:
                prefix = ""
            else:
                prefix = "u"

            typ = "{}int{}_t".format(prefix, res.byte_size)

        elif res.type == "Objlnk":
            typ = "struct lwm2m_objlnk"

        elif res.type == "Float":
            typ = "float32_value_t"

        elif res.type == "Opaque":
            typ = "uint8_t"
            typ_suffix = "[{}]".format(data_len)

        elif res.type == "Time":
            typ = "uint32_t"

        elif res.type == "Boolean":
            typ = "bool"

        else:
            raise Exception("Unhandled / bad resource type")

        yield "\t{} {}{};\n".format(typ, name_format(res.name), typ_suffix)

    yield "}};\n\n".format(name_format(obj.name))

    if not obj.singleton:
        arr_suffix = "[MAX_INSTANCE_COUNT]"
    else:
        arr_suffix = ""
    yield "static {} {}{};\n\n".format(gen_data_struct_type(obj),
                                       gen_data_struct_var_name(obj), arr_suffix)

def gen_field(obj, res):
    if is_exec(res):
        if res.mandatory:
            suffix = ""
        else:
            suffix = "_OPT"
        return "OBJ_FIELD_EXECUTE{}({})".format(suffix, gen_res_id_name(obj, res))


    if res.mandatory:
        ops = res.operations
    else:
        ops = "{}_OPT".format(res.operations)

    if res.type == "String":
        typ = "STRING"
    elif res.type == "Integer":
        if res.signed:
            prefix = "S"
        else:
            prefix = "U"

        typ = "{}{}".format(prefix, res.byte_size)
    elif res.type == "Objlnk":
        typ = "OBJLNK"
    elif res.type == "Float":
        typ = "FLOAT32"
    elif res.type == "Opaque":
        typ = "OPAQUE"
    elif res.type == "Time":
        typ = "TIME"
    elif res.type == "Boolean":
        typ = "BOOL"
    else:
        raise Exception("Unhandled / bad resource type")

    return "OBJ_FIELD_DATA({}, {}, {})".format(gen_res_id_name(obj, res), ops, typ)


def gen_fields(obj):
    if obj.singleton:
        max_inst = ""
    else:
        max_inst = "[MAX_INSTANCE_COUNT]"

    yield "static struct lwm2m_engine_obj {};\n".format(name_format(obj.name))
    yield "static struct lwm2m_engine_obj_field fields[] = {\n"
    for ix, res in enumerate(obj.resources):
        yield "\t{}".format(gen_field(obj, res))

        if ix < len(obj.resources) - 1:
            yield ","
        yield "\n"
    yield "};\n\n"

    yield "static struct lwm2m_engine_obj_inst inst{};\n".format(max_inst)
    yield "static struct lwm2m_engine_res res{}[{}];\n".format(max_inst, gen_max_id(obj))
    yield "static struct lwm2m_engine_res_inst res_inst{}[RESOURCE_INSTANCE_COUNT];\n".format(max_inst)

    yield "\n"

CHECK_AVAIL = """
    /* Check that there is no other instance with this ID */
	for (index = 0; index < ARRAY_SIZE(inst); index++) {
		if (inst[index].obj && inst[index].obj_inst_id == obj_inst_id) {
			LOG_ERR("Can not create instance - "
				"already existing: %u", obj_inst_id);
			return NULL;
		}

		/* Save first available slot index */
		if (avail < 0 && !inst[index].obj) {
			avail = index;
		}
	}

	if (avail < 0) {
		LOG_ERR("Can not create instance - no more room: %u",
			obj_inst_id);
		return NULL;
	}
    """

def gen_exec_cb_name(res):
    return "state_{}_exec_cb".format(name_format(res.name))


def gen_exec_cbs(obj):
    for res in obj.resources:
        if not is_exec(res) or not res.mandatory:
            continue

        yield "static int {}(uint16_t obj_inst_id)\n".format(gen_exec_cb_name(res))
        yield "{\n"
        yield "\t/* FIXME: Add exec callback implementation here */\n"
        yield "\treturn 0;\n"
        yield "}\n\n"


def gen_create_func(obj):
    yield "static struct lwm2m_engine_obj_inst *{}_create(uint16_t obj_inst_id)\n".format(name_format(obj.name))
    yield "{\n"
    yield "\tint i = 0;\n"
    yield "\tint j = 0;\n\n"

    yield "\t/* Set default values */\n"
    if not obj.singleton:
        yield "\tint index = -1;\n";
        yield "\tint avail = -1;\n";
        yield "\t{} *instance;\n".format(gen_data_struct_type(obj));

        yield CHECK_AVAIL
        yield "\tinstance = &{}[avail];\n".format(gen_data_struct_var_name(obj))
        yield "\t(void)memset(instance, 0, sizeof({}[avail]));\n".format(gen_data_struct_var_name(obj))

        data_str = "instance->"
        res_str = "res[avail]"
        res_inst_str = "res_inst[avail]"
        inst_str = "inst[avail]"
    else:
        yield "\t(void)memset(&{0}, 0, sizeof({0}));\n".format(gen_data_struct_var_name(obj))
        data_str = "{}.".format(gen_data_struct_var_name(obj))
        res_str = "res"
        res_inst_str = "res_inst"
        inst_str = "inst"
     
    yield "\t(void)memset({}, 0,\n".format(res_str)
    yield "\t             sizeof({0}[0]) * ARRAY_SIZE({0}));\n\n".format(res_str)
    yield "\tinit_res_instance({0}, ARRAY_SIZE({0}));\n\n".format(res_inst_str)

    yield "\t/* initialize instance resource data */\n"

    for res in obj.resources:

        if is_exec(res):
            yield "\tINIT_OBJ_RES_EXECUTE({}, {}, i,\n".format(gen_res_id_name(obj, res), res_str)
            yield "\t                 "
            if res.mandatory:
                yield gen_exec_cb_name(res)
            else:
                yield "NULL"

            yield ");\n"

        else: # Resource is not execute

            prefix = ""
            if not res.mandatory:
                prefix = "{}OPT".format(prefix)

            if not res.singleton:
                prefix = "MULTI_{}".format(prefix)

            # Yield res init macro. Which one is determined by prefix
            macro = "INIT_OBJ_RES_{}DATA".format(prefix)

            # Calculate how many spaces are needed for indentation
            spaces = " " * len(macro)

            yield "\t{}({},\n".format(macro, gen_res_id_name(obj, res))
            yield "\t{} {}, i, {}, j".format(spaces, res_str, res_inst_str)

            # Add array parameters if needed
            if not res.singleton:
                yield ",\n"
                yield "\t{} {}, false".format(spaces, gen_res_max_name(obj, res))

            # Add data fields if mandatory
            if res.mandatory:
                yield ",\n"
                yield "\t{} &{}{},\n".format(spaces, data_str, name_format(res.name))
                yield "\t{} sizeof({}{})".format(spaces, data_str, name_format(res.name))

            yield ");\n"

    yield "\n\t{}.resources = {};\n".format(inst_str, res_str)
    yield "\t{}.resource_count = i;\n".format(inst_str)

    yield "\n\tLOG_DBG(\"Create {} instance: %d\", obj_inst_id);\n\n".format(obj.name)

    yield "\treturn &{};\n".format(inst_str)
    yield "}\n\n"


def gen_init_func(obj):
    yield "static int lwm2m_{}_init(const struct device *dev)\n".format(name_format(obj.name))
    yield "{\n"

    if (obj.singleton):
        yield "\tstruct lwm2m_engine_obj_inst *obj_inst;\n"
        yield "\tint ret;\n\n"

    yield "\t{}.obj_id = {};\n".format(name_format(obj.name), gen_obj_id_def(obj))
    yield "\t{}.fields = fields;\n".format(name_format(obj.name))
    yield "\t{}.field_count = ARRAY_SIZE(fields);\n".format(name_format(obj.name))

    if (obj.singleton):
        yield "\t{}.max_instance_count = 1;\n".format(name_format(obj.name))
    else:
        yield "\t{}.max_instance_count = MAX_INSTANCE_COUNT;\n".format(name_format(obj.name))

    yield "\t{0}.create_cb = {0}_create;\n".format(name_format(obj.name))
    yield "\tlwm2m_register_obj(&{});\n\n".format(name_format(obj.name))

    if (obj.singleton):
        yield "\t/* auto create the only instance */\n"
        yield "\tobj_inst = NULL;\n"
        yield "\tret = lwm2m_create_obj_inst("
        yield "{}, 0, &obj_inst);\n".format(gen_obj_id_def(obj))
        yield "\tif (ret < 0) {\n"
        yield "\t\tLOG_DBG(\"Create LWM2M instance 0 error: %d\", ret);\n"
        yield "\t}\n\n"
        yield "\treturn ret;\n"
    else:
        yield "\treturn 0;\n"
    yield "}\n\n"

    yield "SYS_INIT(lwm2m_{}_init, APPLICATION, ".format(name_format(obj.name))
    yield "CONFIG_KERNEL_INIT_PRIORITY_DEFAULT);\n"

def main():
    if (len(sys.argv) < 2):
            print("No argument given. The path XML file descirbing")
            print("the LWM2M object in question is expected as argument")
            print("\nExampel 'gen.py 3.xml'")
            return

    tree = ET.parse(sys.argv[1])
    root = tree.getroot()

    obj = LWM2MObject(root.find("Object"))

    with open("lwm2m_obj_{}_stub.c".format(name_format(obj.name)), "w") as f:
        f.writelines(gen_file_head(obj))
        f.writelines(gen_res_defs(obj))
        f.writelines(gen_res_inst_count(obj))
        f.writelines(gen_data_struct(obj))
        f.writelines(gen_fields(obj))
        f.writelines(gen_exec_cbs(obj))
        f.writelines(gen_create_func(obj))
        f.writelines(gen_init_func(obj))


if __name__ == "__main__":
    main()
