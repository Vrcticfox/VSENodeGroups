import bpy
import os
import wave

from bpy.props import (
    StringProperty,
    FloatProperty,
    IntProperty,
    BoolProperty,
    EnumProperty,
    PointerProperty,
)


# ------------------------------------------------------------
# Utility
# ------------------------------------------------------------

def try_detect_wav_nyquist(filepath):
    """
    WAV 파일이면 sample rate를 읽어서 Nyquist frequency를 반환.
    MP3/OGG 등은 Python 표준 wave 모듈로 읽을 수 없으므로 None 반환.
    """
    if not filepath:
        return None

    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".wav":
        return None

    try:
        with wave.open(filepath, "rb") as wf:
            sample_rate = wf.getframerate()
            return sample_rate * 0.5
    except Exception:
        return None


def make_log_bands(min_freq, max_freq, band_count):
    """
    min_freq ~ max_freq를 로그 스케일로 band_count개 분할.
    0번 막대 = 최저 주파수
    마지막 막대 = 최고 주파수
    """
    min_freq = max(1.0, float(min_freq))
    max_freq = max(min_freq + 1.0, float(max_freq))
    band_count = max(1, int(band_count))

    ratio = (max_freq / min_freq) ** (1.0 / band_count)

    bands = []
    for i in range(band_count):
        low = min_freq * (ratio ** i)
        high = min_freq * (ratio ** (i + 1))
        bands.append((low, high))

    return bands


def sort_objects(objs, axis):
    if axis == "X":
        return sorted(objs, key=lambda o: o.location.x)
    if axis == "Y":
        return sorted(objs, key=lambda o: o.location.y)
    if axis == "Z":
        return sorted(objs, key=lambda o: o.location.z)
    if axis == "NAME":
        return sorted(objs, key=lambda o: o.name)

    return objs


def ensure_graph_editor_context(context):
    """
    sound_to_samples는 Graph Editor 컨텍스트가 필요하다.
    Graph Editor가 없으면 현재 area를 잠깐 Graph Editor로 바꾼다.
    """
    screen = context.screen
    current_area = context.area

    for area in screen.areas:
        if area.type == "GRAPH_EDITOR":
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            if region:
                return area, region, None

    old_type = current_area.type
    current_area.type = "GRAPH_EDITOR"
    region = next((r for r in current_area.regions if r.type == "WINDOW"), None)

    return current_area, region, old_type


def call_sound_to_samples(filepath, low, high, attack, release, threshold, use_square):
    """
    Blender 버전별 Sound to Samples / Sound Bake 이름 차이를 흡수하기 위한 래퍼.

    중요:
    use_accumulate=False
    use_additive=False

    이 둘을 꺼야 사운드바처럼 들쭉날쭉한 커브가 나오고,
    계속 누적돼서 올라가는 커브가 되지 않는다.
    """

    # Blender 5.x 계열
    try:
        bpy.ops.graph.sound_to_samples(
            filepath=filepath,
            low=low,
            high=high,
            attack=attack,
            release=release,
            threshold=threshold,
            use_accumulate=False,
            use_additive=False,
            use_square=use_square,
            sthreshold=0.1,
        )
        return
    except Exception as e_first:
        first_error = e_first

    # 구버전 호환용
    try:
        bpy.ops.graph.sound_bake(
            filepath=filepath,
            low=low,
            high=high,
            attack=attack,
            release=release,
            threshold=threshold,
            use_accumulate=False,
            use_additive=False,
            use_square=use_square,
            sthreshold=0.1,
        )
        return
    except Exception as e_second:
        raise RuntimeError(
            "Sound to Samples 실행 실패.\n"
            f"sound_to_samples error: {first_error}\n"
            f"sound_bake error: {e_second}"
        )


def iter_action_fcurves(action):
    """
    Blender 4.x 구 API / Blender 5.x 신 API 양쪽 대응용.
    """
    # Blender 4.x 이하 또는 Legacy Action
    if hasattr(action, "fcurves"):
        for fcu in action.fcurves:
            yield fcu
        return

    # Blender 5.x Action Slot / Channelbag API
    try:
        from bpy_extras import anim_utils

        for slot in action.slots:
            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
            if channelbag is None:
                continue

            for fcu in channelbag.fcurves:
                yield fcu

    except Exception:
        return


def clear_fcurve_selections():
    for action in bpy.data.actions:
        for fcu in iter_action_fcurves(action):
            fcu.select = False

            for kp in fcu.keyframe_points:
                kp.select_control_point = False


def get_channelbag_for_object(obj):
    """
    Blender 5.x에서 현재 오브젝트의 Action Slot에 대응되는 Channelbag 반환.
    없으면 생성.
    """
    if obj.animation_data is None:
        obj.animation_data_create()

    if obj.animation_data.action is None:
        obj.animation_data.action = bpy.data.actions.new(
            obj.name + "_SpectrumAction"
        )

    action = obj.animation_data.action

    if obj.animation_data.action_slot is None:
        obj.keyframe_insert(
            data_path="scale",
            index=2,
            frame=bpy.context.scene.frame_start
        )

    from bpy_extras import anim_utils

    return anim_utils.action_ensure_channelbag_for_slot(
        action,
        obj.animation_data.action_slot
    )


def remove_scale_z_fcurve(obj):
    """
    기존 scale.z F-Curve 제거.
    Blender 4.x / 5.x 양쪽 대응.
    """
    if obj.animation_data is None:
        return

    action = obj.animation_data.action
    if action is None:
        return

    # 구 API
    if hasattr(action, "fcurves"):
        old_fcu = action.fcurves.find("scale", index=2)
        if old_fcu:
            action.fcurves.remove(old_fcu)
        return

    # Blender 5.x
    try:
        channelbag = get_channelbag_for_object(obj)
        old_fcu = channelbag.fcurves.find("scale", index=2)
        if old_fcu:
            channelbag.fcurves.remove(old_fcu)
    except Exception:
        pass


def find_scale_z_fcurve(obj):
    """
    obj의 scale.z F-Curve 찾기.
    Blender 4.x / 5.x 양쪽 대응.
    """
    if obj.animation_data is None:
        return None

    action = obj.animation_data.action
    if action is None:
        return None

    # 구 API
    if hasattr(action, "fcurves"):
        return action.fcurves.find("scale", index=2)

    # Blender 5.x 권장 경로 우선
    try:
        fcu = action.fcurve_ensure_for_datablock(
            obj,
            "scale",
            index=2,
            group_name="Transform"
        )
        if fcu:
            return fcu
    except Exception:
        pass

    # Channelbag fallback
    try:
        channelbag = get_channelbag_for_object(obj)
        return channelbag.fcurves.find("scale", index=2)
    except Exception:
        return None


def prepare_scale_z_fcurve(obj, frame, base_scale_z, clear_existing):
    """
    오브젝트의 scale.z F-Curve를 만들고 선택 상태로 만든다.
    Blender 4.x / 5.x 대응.
    """
    if obj.animation_data is None:
        obj.animation_data_create()

    if obj.animation_data.action is None:
        obj.animation_data.action = bpy.data.actions.new(
            obj.name + "_SpectrumAction"
        )

    if clear_existing:
        remove_scale_z_fcurve(obj)

    obj.scale.z = base_scale_z
    obj.keyframe_insert(data_path="scale", index=2, frame=frame)

    fcu = find_scale_z_fcurve(obj)

    if fcu is None:
        raise RuntimeError(f"{obj.name}: scale.z F-Curve 생성 실패")

    clear_fcurve_selections()

    fcu.select = True

    for kp in fcu.keyframe_points:
        kp.select_control_point = True

    return fcu


def shift_fcurve_frames(fcu, frame_offset):
    """
    F-Curve 전체를 X축, 즉 시간축으로 frame_offset만큼 이동.
    Prefix Frames 용도.

    frame_offset = 15  → 15프레임 뒤로 밀림
    frame_offset = -5  → 5프레임 앞으로 당김
    """
    if fcu is None or frame_offset == 0:
        return

    # 일반 키프레임 이동
    for kp in fcu.keyframe_points:
        kp.co.x += frame_offset
        kp.handle_left.x += frame_offset
        kp.handle_right.x += frame_offset

    # Sound to Samples 결과가 sampled_points로 들어간 경우 대응
    if hasattr(fcu, "sampled_points"):
        for sp in fcu.sampled_points:
            try:
                sp.co.x += frame_offset
            except Exception:
                pass

    try:
        fcu.update()
    except Exception:
        pass


# ------------------------------------------------------------
# Properties
# ------------------------------------------------------------

class AUDIO_SPECTRUM_Properties(bpy.types.PropertyGroup):
    audio_path: StringProperty(
        name="Audio File",
        subtype="FILE_PATH",
        default=""
    )

    min_freq: FloatProperty(
        name="Min Frequency",
        description="첫 번째 막대가 담당할 최저 주파수",
        default=30.0,
        min=1.0,
        soft_max=1000.0
    )

    max_freq: FloatProperty(
        name="Max Frequency",
        description="마지막 막대가 담당할 최고 주파수",
        default=16000.0,
        min=100.0,
        soft_max=24000.0
    )

    auto_wav_max: BoolProperty(
        name="Auto Max From WAV",
        description="WAV 파일이면 sample rate / 2를 감지해서 max frequency 상한으로 사용",
        default=True
    )

    sort_axis: EnumProperty(
        name="Sort Objects",
        description="막대 순서를 정하는 기준. 첫 번째 오브젝트가 최저 주파수, 마지막 오브젝트가 최고 주파수",
        items=[
            ("X", "X Location", "X 위치 기준 정렬"),
            ("Y", "Y Location", "Y 위치 기준 정렬"),
            ("Z", "Z Location", "Z 위치 기준 정렬"),
            ("NAME", "Name", "이름 기준 정렬"),
        ],
        default="X"
    )

    reverse_order: BoolProperty(
        name="Reverse Order",
        description="체크하면 첫 번째 오브젝트가 최고 주파수, 마지막 오브젝트가 최저 주파수",
        default=False
    )

    base_scale_z: FloatProperty(
        name="Base Scale Z",
        description="Bake 전 기본 Scale Z",
        default=0.1,
        min=0.001,
        soft_max=5.0
    )

    prefix_frames: IntProperty(
        name="Prefix Frames",
        description="Bake 후 생성된 사운드 커브를 이 프레임 수만큼 뒤로 민다. 15면 15프레임 뒤에서 시작",
        default=0,
        min=-10000,
        max=10000
    )

    attack: FloatProperty(
        name="Attack",
        default=0.005,
        min=0.0,
        soft_max=1.0
    )

    release: FloatProperty(
        name="Release",
        default=0.2,
        min=0.0,
        soft_max=2.0
    )

    threshold: FloatProperty(
        name="Threshold",
        default=0.0,
        min=0.0,
        soft_max=1.0
    )

    use_square: BoolProperty(
        name="Use Square",
        description="반응을 더 강하게 만들 수 있음. 단, 너무 과하면 튈 수 있음",
        default=False
    )

    clear_existing: BoolProperty(
        name="Clear Existing Scale Z",
        description="기존 Scale Z 애니메이션을 지우고 새로 bake",
        default=True
    )


# ------------------------------------------------------------
# Operator
# ------------------------------------------------------------

class AUDIO_SPECTRUM_OT_bake_selected(bpy.types.Operator):
    bl_idname = "audio_spectrum.bake_selected"
    bl_label = "Bake Selected Bars"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.audio_spectrum_props

        filepath = bpy.path.abspath(props.audio_path)

        if not filepath or not os.path.exists(filepath):
            self.report({"ERROR"}, "오디오 파일 경로가 잘못됨")
            return {"CANCELLED"}

        objs = [
            obj for obj in context.selected_objects
            if obj.type == "MESH"
        ]

        if not objs:
            self.report({"ERROR"}, "선택된 Mesh 오브젝트가 없음")
            return {"CANCELLED"}

        objs = sort_objects(objs, props.sort_axis)

        if props.reverse_order:
            objs.reverse()

        min_freq = props.min_freq
        max_freq = props.max_freq

        if props.auto_wav_max:
            nyquist = try_detect_wav_nyquist(filepath)
            if nyquist is not None:
                max_freq = min(max_freq, nyquist)

        if max_freq <= min_freq:
            self.report({"ERROR"}, "Max Frequency가 Min Frequency보다 커야 함")
            return {"CANCELLED"}

        band_count = len(objs)
        bands = make_log_bands(min_freq, max_freq, band_count)

        original_active = context.view_layer.objects.active
        original_selected = list(context.selected_objects)

        area, region, old_area_type = ensure_graph_editor_context(context)

        if region is None:
            self.report({"ERROR"}, "Graph Editor 영역 생성 실패")
            return {"CANCELLED"}

        scene = context.scene
        frame = scene.frame_start

        try:
            for obj_index, obj in enumerate(objs):
                low, high = bands[obj_index]

                for o in context.scene.objects:
                    o.select_set(False)

                obj.select_set(True)
                context.view_layer.objects.active = obj

                prepare_scale_z_fcurve(
                    obj=obj,
                    frame=frame,
                    base_scale_z=props.base_scale_z,
                    clear_existing=props.clear_existing
                )

                with context.temp_override(
                    area=area,
                    region=region,
                    active_object=obj,
                    selected_objects=[obj],
                    object=obj,
                    scene=scene,
                    screen=context.screen,
                    window=context.window,
                ):
                    call_sound_to_samples(
                        filepath=filepath,
                        low=low,
                        high=high,
                        attack=props.attack,
                        release=props.release,
                        threshold=props.threshold,
                        use_square=props.use_square,
                    )

                fcu = find_scale_z_fcurve(obj)
                shift_fcurve_frames(fcu, props.prefix_frames)

                print(
                    f"[Audio Spectrum Bake] #{obj_index:02d} {obj.name}: "
                    f"{low:.2f} Hz ~ {high:.2f} Hz, "
                    f"prefix {props.prefix_frames} frames"
                )

        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        finally:
            if old_area_type is not None:
                area.type = old_area_type

            for o in context.scene.objects:
                o.select_set(False)

            for o in original_selected:
                if o.name in bpy.data.objects:
                    o.select_set(True)

            if original_active and original_active.name in bpy.data.objects:
                context.view_layer.objects.active = original_active

        self.report(
            {"INFO"},
            f"{len(objs)}개 오브젝트에 단방향 로그 주파수 bake 완료"
        )

        return {"FINISHED"}


# ------------------------------------------------------------
# Panel
# ------------------------------------------------------------

class AUDIO_SPECTRUM_PT_panel(bpy.types.Panel):
    bl_label = "Audio Spectrum Baker"
    bl_idname = "AUDIO_SPECTRUM_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Audio Spectrum"

    def draw(self, context):
        layout = self.layout
        props = context.scene.audio_spectrum_props

        layout.prop(props, "audio_path")

        layout.separator()

        layout.prop(props, "min_freq")
        layout.prop(props, "max_freq")
        layout.prop(props, "auto_wav_max")

        layout.separator()

        layout.label(text="Order")
        layout.prop(props, "sort_axis")
        layout.prop(props, "reverse_order")

        layout.separator()

        layout.prop(props, "base_scale_z")
        layout.prop(props, "prefix_frames")

        layout.separator()

        layout.prop(props, "attack")
        layout.prop(props, "release")
        layout.prop(props, "threshold")
        layout.prop(props, "use_square")
        layout.prop(props, "clear_existing")

        layout.separator()

        selected_mesh_count = len([
            obj for obj in context.selected_objects
            if obj.type == "MESH"
        ])

        layout.label(text=f"Selected Meshes: {selected_mesh_count}")

        if selected_mesh_count > 0:
            layout.label(text="First Bar = Low Frequency")
            layout.label(text="Last Bar = High Frequency")

        layout.operator("audio_spectrum.bake_selected", icon="SOUND")


# ------------------------------------------------------------
# Register
# ------------------------------------------------------------

classes = (
    AUDIO_SPECTRUM_Properties,
    AUDIO_SPECTRUM_OT_bake_selected,
    AUDIO_SPECTRUM_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.audio_spectrum_props = PointerProperty(
        type=AUDIO_SPECTRUM_Properties
    )


def unregister():
    if hasattr(bpy.types.Scene, "audio_spectrum_props"):
        del bpy.types.Scene.audio_spectrum_props

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
