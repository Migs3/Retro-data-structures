import construct
from construct import (Struct, Int32ub, Const, Array, Aligned, PrefixedArray, If, Int16ub, Byte, Float32b,
                       GreedyRange, IfThenElse, Float16b, Bytes, Switch, Int8ub, Rebuild, Prefixed, Pointer,
                       FocusedSeq, Tell)

from retro_data_structures.common_types import AABox, AssetId32, Vector3, Color4f, Vector2f
from retro_data_structures.construct_extensions import AlignTo, WithVersion

TEVStage = Struct(
    color_input_flags=Int32ub,
    alpha_input_flags=Int32ub,
    color_combine_flags=Int32ub,
    alpha_combine_flags=Int32ub,
    padding=Byte,
    konst_alpha_input=Byte,
    konst_color_input=Byte,
    rasterized_color_input=Byte,
)

TEVInput = Struct(
    padding=Int16ub,
    texture_tev_input=Byte,
    tex_coord_tev_input=Byte,
)

param_count_per_uv_animtion_type = {
    0: 0,
    1: 0,
    2: 4,
    3: 2,
    4: 4,
    5: 4,
    6: 0,
    7: 2,
    8: 9,
}

UVAnimation = Struct(
    animation_type=Int32ub,
    parameters=Array(lambda this: param_count_per_uv_animtion_type[this.animation_type], Float32b),
)

Material = Struct(
    flags=Int32ub,
    texture_indices=PrefixedArray(Int32ub, Int32ub),
    vertex_attribute_flags=Int32ub,
    unk_1=WithVersion(4, Int32ub),
    unk_2=WithVersion(4, Int32ub),
    group_index=Int32ub,
    konst_colors=If(construct.this.flags & 0x8, PrefixedArray(Int32ub, Int32ub)),
    blend_destination_factor=Int16ub,
    blend_source_factor=Int16ub,
    reflection_indirect_texture_slot_index=If(construct.this.flags & 0x400, Int32ub),
    color_channel_flags=PrefixedArray(Int32ub, Int32ub),

    tev_stage_count=Int32ub,
    tev_stages=Array(construct.this.tev_stage_count, TEVStage),
    tev_inputs=Array(construct.this.tev_stage_count, TEVInput),

    texgen_flags=PrefixedArray(Int32ub, Int32ub),

    material_animations_section_size=Int32ub,
    uv_animations=PrefixedArray(Int32ub, UVAnimation),
)

MaterialSet = Struct(
    texture_file_ids=PrefixedArray(Int32ub, AssetId32),
    material_count=Int32ub,
    material_end_offsets=Array(construct.this.material_count, Int32ub),
    materials=Array(construct.this.material_count, Material),
)


def get_material(context):
    surface = context
    while 'header' not in surface:
        surface = surface['_']
    return context._root.material_sets[0].materials[surface.header.material_index]


def VertexAttrib(flag):
    if not flag:
        raise ValueError("Invalid flag!")

    shift = 0
    while (flag >> shift) & 1 == 0:
        shift += 1

    return Switch(
        lambda this: (get_material(this).vertex_attribute_flags & flag) >> shift,
        {
            3: Int16ub,
            2: Int8ub,
            1: Int8ub,
        }
    )


Surface = Struct(
    header=Aligned(32, Struct(
        center_point=Vector3,
        material_index=Int32ub,
        mantissa=Int16ub,
        display_list_size=Int16ub,
        parent_model_pointer_storage=Int32ub,
        next_surface_pointer_storage=Int32ub,
        extra_data_size=Int32ub,
        surface_normal=Vector3,
        unk_1=WithVersion(4, Int16ub),
        unk_2=WithVersion(4, Int16ub),
        extra_data=Bytes(construct.this.extra_data_size),
    )),
    primitives=GreedyRange(Struct(
        type=Byte,
        vertices=PrefixedArray(Int16ub, Struct(
            matrix=Struct(
                position=VertexAttrib(0x01 << 24),
                tex=Struct(*[
                    str(i) / VertexAttrib(flag << 24)
                    for i, flag in enumerate([0x02, 0x04, 0x08, 0x10,
                                              0x20, 0x40, 0x80])
                ]),
            ),
            position=VertexAttrib(0x03),
            normal=VertexAttrib(0x0c),
            color_0=VertexAttrib(0x30),
            color_1=VertexAttrib(0xc0),
            tex=Struct(*[
                str(i) / VertexAttrib(flag)
                for i, flag in enumerate([0x00000300, 0x00000C00, 0x00003000, 0x0000C000,
                                          0x00030000, 0x000C0000, 0x00300000, 0x00C00000])
            ]),
        ))
    )),
)


def DataSectionSizes(section_count):
    return Array(section_count, FocusedSeq(
        "address",
        address=Tell,
        value=construct.Seek(4, 1),
    ))


def DataSection(subcon):
    def get_section_length_address(context):
        root = context["_root"]
        index = root["_current_section"]
        root["_current_section"] += 1
        return root._data_section_sizes[index]

    return Prefixed(Pointer(get_section_length_address, Int32ub), subcon)


# 0x2 = Prime 1
# 0x4 = Prime 2
# 0x5 = Prime 3
CMDL = Struct(
    magic=Const(0xDEADBABE, Int32ub),
    version=Int32ub,
    flags=Int32ub,
    aabox=AABox,
    _data_section_count=Rebuild(
        Int32ub,
        lambda context: (len(context.material_sets)
                         + sum(1 for k, v in context.attrib_arrays.items()
                               if not k.startswith("_") and v is not None)
                         + 1
                         + len(context.surfaces)),
    ),
    _material_set_count=Rebuild(Int32ub, construct.len_(construct.this.material_sets)),
    _data_section_sizes=DataSectionSizes(construct.this._data_section_count),
    _=AlignTo(32),
    _current_section=construct.Computed(lambda this: 0),
    material_sets=Array(construct.this._material_set_count, DataSection(Aligned(32, MaterialSet))),
    attrib_arrays=Struct(
        positions=DataSection(GreedyRange(Vector3)),
        normals=DataSection(
            GreedyRange(IfThenElse(
                construct.this._root.flags & 0x2,
                construct.Error,  # TODO: read the half-vectors
                Vector3,
            )),
        ),
        # TODO: none of Retro's games actually have data here, so this might be the wrong type!
        colors=DataSection(GreedyRange(Color4f)),
        uvs=DataSection(GreedyRange(Vector2f)),
        lightmap_uvs=If(
            construct.this._root.flags & 0x4,
            DataSection(GreedyRange(Array(2, Float16b))),
        ),
    ),
    surface_header=DataSection(Aligned(32, Struct(
        _num_surfaces=Rebuild(Int32ub, construct.len_(construct.this["_"].surfaces)),
        offsets=Array(construct.this._num_surfaces, Int32ub),
    ))),
    surfaces=Array(
        construct.this.surface_header._num_surfaces,
        DataSection(Aligned(32, Surface)),
    ),
)