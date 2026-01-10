# VSENodeGroups
개인용으로 쓰려고 저장한 영상편집용 블렌더 노드그룹. 만들때마다 추가할꺼임

# How to Use
1. `Blender 5.0+` 설치.
2. `File` - `Link` or `Append` - .blend file 선택.
3. `Video Sequencer` timeline 에서, 효과를 적용할 **Strip** 선택.
4. Strip Modifier 에서 `Compositor` 추가.
5. `Composite` 창 열고, `Node Tree Sub-Type` 를 `Sequencer`로 변경. (기본값은 `Scene`임.)
6. `Asset Library` 로부터 효과 노드그룹을 불러와 사용.

# List
- [ColorizeTP](.blend/ColorizeTP.blend) : 대상 영역에 Background Color 기반의 Colorize 효과

# Example
| ![ColorizeTP](example/ColorizeTP.gif) |
| :---: |
| ColorizeTP |
