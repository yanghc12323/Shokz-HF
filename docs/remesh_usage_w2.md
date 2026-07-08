# W2 Patch-Based Remesh 浣跨敤璇存槑

> 鏇存柊鏃堕棿锛?026-07-08  
> 閫傜敤鑼冨洿锛歐2 闃舵 1 鍒伴樁娈?11 鐨勮鏂囧紡 remesh 鍘熷瀷  
> 浠ｇ爜鍏ュ彛锛歚ear_param/remesh.py`

## 1. 杩欎釜妯″潡鐜板湪鑳藉仛浠€涔?
褰撳墠鏂板鐨?`ear_param.remesh` 妯″潡瀹炵幇鐨勬槸 W2 涓€滃畬鏁磋鏂囧紡 remesh鈥濈殑涓讳綋娴佺▼锛屼篃灏辨槸浠庡師濮嬭€虫湹 mesh 鍜?landmark-defined triangle 鍑哄彂锛屽緱鍒颁竴涓浐瀹氭ā鏉夸笂鐨?3D remesh patch锛屽苟杈撳嚭鏈懆楠屾敹闇€瑕佺殑鐐广€侀潰銆乵esh銆丵C 鍜?landmark 鍑犱綍鐗瑰緛鍊笺€?
宸插疄鐜扮殑 8 涓樁娈靛涓嬶細

| 闃舵 | 鍑芥暟 | 浣滅敤 |
|---|---|---|
| 1 | `snap_landmarks_to_vertices` | 灏?landmark 鍧愭爣鍚搁檮鍒版渶杩戠殑 mesh 椤剁偣 |
| 2 | `build_mesh_adjacency` | 鏍规嵁 mesh faces 鏋勫缓鍔犳潈椤剁偣鍥?|
| 3 | `build_triangle_boundary_paths` | 鍦?mesh 鍥句笂璁＄畻涓変釜 landmark 涔嬮棿鐨勬渶鐭竟鐣岃矾寰?|
| 4 | `extract_patch_faces` | 鐢ㄤ笁鏉¤竟鐣岃矾寰勫垏鍒?mesh face graph锛屾彁鍙栧眬閮ㄤ笁瑙?patch |
| 5 | `PatchExtraction` 缁撴灉瀵硅薄 | 灏?patch 杞垚灞€閮ㄩ《鐐瑰拰灞€閮ㄩ潰鐗囩储寮?|
| 6 | `harmonic_parameterize_patch` | 灏?patch harmonic parameterization 鍒版爣鍑?2D 涓夎鍩?|
| 7 | `make_subdivision_template` | 鍦ㄦ爣鍑嗕笁瑙掑煙涓敓鎴愬浐瀹氭暟閲忛噰鏍风偣鍜屾ā鏉夸笁瑙掗潰 |
| 8 | `locate_uv_samples_in_faces` + `map_samples_to_3d` | 鎵惧埌姣忎釜 2D 妯℃澘鐐规墍鍦ㄦ簮 UV 闈㈢墖锛屽苟鏄犲皠鍥?3D |
| 9 | `build_region_remesh_mesh` | 浣跨敤 `sample_points_3d + template.faces` 缁勮鍗曞尯鍩?remesh mesh |
| 10 | `scripts/parameterize_ear_remesh.py` | 杈撳嚭 points/faces/features/QC/PLY |
| 11 | `T001_L_remesh_qc.csv` | 鐢ㄥ浐瀹氱偣鏁般€乽nmapped銆乨egenerate銆乵esh 瀵煎嚭鐘舵€佽繘琛岄獙鏀?|

鎺ㄨ崘浣跨敤鎬诲叆鍙ｏ細

```python
from ear_param.remesh import build_region_remesh

result = build_region_remesh(mesh, landmarks, region)
```

杩欎釜鍏ュ彛浼氶『搴忔墽琛岄樁娈?1 鍒伴樁娈?8銆?
## 2. 瀹冨拰鍘熸潵鐨勫弬鏁板寲閲囨牱鏈変粈涔堝尯鍒?
鍘熸潵鐨勪富娴佺▼鍦?`ear_param/core.py` 鍜?`scripts/parameterize_ear.py` 涓紝涓昏杈撳嚭鈥滃弬鏁板寲閲囨牱鐐逛簯鈥濄€傚畠淇濈暀鍥哄畾閲囨牱鐐规暟閲忥紝浣嗕笉鐢熸垚绋冲畾鐨?remesh 闈㈢墖鎷撴墤銆?
鏂扮殑 `ear_param/remesh.py` 鏄嫭绔嬫ā鍧楋紝鐩爣鏄鏂囧紡 cross-parameterisation锛?
- 姣忎釜鍖哄煙鍏堜粠鍘熷 mesh 涓婃彁鍙栫湡瀹炰笁瑙?patch銆?- patch 琚睍寮€鍒扮粺涓€鐨?2D 鏍囧噯涓夎鍩熴€?- 鍦?2D 鏍囧噯涓夎鍩熶腑鐢熸垚鍥哄畾 subdivision template銆?- template 鐐瑰啀鏄犲皠鍥炴瘡涓牱鏈殑 3D 鏇查潰銆?- 鍥犱负 template faces 鏄浐瀹氱殑锛屾墍浠ュ悗缁彲浠ュ舰鎴愯法鏍锋湰鍚屾嫇鎵?remesh patch銆?
鐩墠涓轰簡灏藉彲鑳藉皬鍦颁慨鏀归」鐩紝鏂版ā鍧楁病鏈夋浛鎹㈠師鏉ョ殑 `scripts/parameterize_ear.py` 娴佺▼锛岃€屾槸閫氳繃鐙珛鍏ュ彛 `scripts/parameterize_ear_remesh.py` 杩愯銆?
## 2.1 褰撳墠鎺ㄨ崘鍛戒护

```powershell
python scripts/parameterize_ear_remesh.py --sample_id T001 --side L --mesh data/clean_mesh/T001_L.ply --landmarks data/landmarks/T001_L_landmarks.csv
```

榛樿浣跨敤锛?
```text
--regions config/region_table.csv
--out_dir output/parameterized_points
--mesh_out_dir output/remesh
```

褰撳墠浼氱敓鎴愶細

```text
output/parameterized_points/T001_L_remesh_points.csv
output/parameterized_points/T001_L_remesh_faces.csv
output/parameterized_points/T001_L_region_features.csv
output/parameterized_points/T001_L_remesh_qc.csv
output/remesh/T001_L/T001_remesh.ply
```

## 3. 杈撳叆鏂囦欢瑕佹眰

### 3.1 Mesh

璺緞绀轰緥锛?
```text
data/clean_mesh/S001_R.ply
```

瑕佹眰锛?
- 鍙互琚?`trimesh.load_mesh(..., process=False)` 鍔犺浇銆?- 蹇呴』鍖呭惈 vertices 鍜?triangular faces銆?- 褰撳墠娴嬭瘯鏁版嵁姣忎釜鏍锋湰绾︿负 6400 vertices / 12482 faces銆?
### 3.2 Landmarks

璺緞绀轰緥锛?
```text
data/landmarks/S001_R_landmarks.csv
```

蹇呰鍒楋細

```text
landmark_id,x,y,z
```

璇诲彇鍚庡繀椤诲皢 `landmark_id` 璁剧疆涓虹储寮曪細

```python
landmarks = pd.read_csv("data/landmarks/S001_R_landmarks.csv").set_index("landmark_id")
```

### 3.3 Region Table

璺緞绀轰緥锛?
```text
config/region_table.csv
```

蹇呰鍒楋細

```text
region_id,region_name,lm_a,lm_b,lm_c,resolution
```

鍏朵腑锛?
- `lm_a/lm_b/lm_c` 鏄笁瑙掑尯鍩熺殑涓変釜 landmark銆?- `resolution` 鎺у埗鏍囧噯涓夎鍩熺粏鍒嗗瘑搴︺€?- 褰撳墠 `resolution=8` 鏃讹紝姣忎釜鍖哄煙鏈?45 涓ā鏉跨偣鍜?64 涓ā鏉夸笁瑙掗潰銆?
## 4. 鏈€灏忎娇鐢ㄧず渚?
鍦ㄩ」鐩牴鐩綍 `D:\YHC\浜哄ご椤圭洰` 涓嬭繍琛岋細

```powershell
@'
from pathlib import Path
import pandas as pd
import trimesh
from ear_param.remesh import build_region_remesh

sample_id = "S001_R"
mesh = trimesh.load_mesh(Path("data/clean_mesh") / f"{sample_id}.ply", process=False)
landmarks = pd.read_csv(Path("data/landmarks") / f"{sample_id}_landmarks.csv").set_index("landmark_id")
regions = pd.read_csv(Path("config/region_table.csv"))

for region in regions.to_dict("records"):
    result = build_region_remesh(mesh, landmarks, region)
    print(
        region["region_id"],
        "patch_faces=", len(result.patch.face_ids),
        "template_points=", len(result.template.barycentric),
        "template_faces=", len(result.template.faces),
        "unmapped=", result.located_samples.unmapped_count,
        "flipped=", result.parameterization.flipped_face_count,
        "degenerate=", result.parameterization.degenerate_face_count,
    )
'@ | python -
```

杈撳嚭涓渶閲嶈鐨勬槸锛?
- `patch_faces`锛氳 region 浠庡師濮?mesh 涓彁鍙栦簡澶氬皯涓簮闈㈢墖銆?- `template_points`锛氳 region 鐨勫浐瀹氶噰鏍风偣鏁伴噺銆?- `template_faces`锛氳 region 鐨勫浐瀹?remesh 闈㈡暟閲忋€?- `unmapped`锛氭湁澶氬皯涓?2D 妯℃澘鐐规病鏈夎惤鍏ユ簮 UV 闈㈢墖銆傜悊鎯冲€兼槸 0銆?- `flipped`锛歎V 闈㈢墖鏂瑰悜涓庢爣鍑嗘柟鍚戠浉鍙嶇殑鏁伴噺銆傝嫢鏁翠釜 patch 閮?flipped锛岄€氬父璇存槑婧?mesh winding 涓庢爣鍑嗕笁瑙掓柟鍚戠浉鍙嶏紝闇€瑕佺粨鍚?`unmapped` 涓€璧风湅銆?- `degenerate`锛歎V 閫€鍖栭潰鏁伴噺銆傜悊鎯冲€兼槸 0銆?
## 5. 缁撴灉瀵硅薄鎬庝箞鐞嗚В

`build_region_remesh(...)` 杩斿洖 `RegionRemeshResult`銆?
甯哥敤瀛楁锛?
```python
result.region_id
result.region_name
result.snapped_landmarks
result.boundary_paths
result.patch
result.parameterization
result.template
result.located_samples
result.sample_points_3d
```

鍏朵腑鏈€鍏抽敭鐨勬槸锛?
```python
result.sample_points_3d
```

瀹冩槸褰㈢姸涓?`(N, 3)` 鐨勬暟缁勶紝琛ㄧず璇?region 鐨勫浐瀹氭ā鏉跨偣鏄犲皠鍥?3D 鍚庣殑鍧愭爣銆?
鍙︿竴涓叧閿瓧娈垫槸锛?
```python
result.template.faces
```

瀹冩槸褰㈢姸涓?`(M, 3)` 鐨勬暟缁勶紝琛ㄧず鍥哄畾妯℃澘涓夎闈㈢殑杩炴帴鍏崇郴銆傚浜庡悓涓€涓?`resolution`锛屾墍鏈夋牱鏈殑 `result.template.faces` 閮界浉鍚屻€?
鍥犳锛屽崟涓?region 鐨?remesh patch 鍙互鐞嗚В涓猴細

```python
vertices = result.sample_points_3d
faces = result.template.faces
```

浣嗚娉ㄦ剰锛氬鏋?`result.located_samples.unmapped_count > 0`锛屽垯 `vertices` 涓細鏈夐儴鍒?`NaN`锛岃繖涓?region 鏆傛椂涓嶈兘鐩存帴鐢ㄤ簬鍚庣画 PCA銆?
## 6. 褰撳墠浠撳簱鏁版嵁鐨勮瘯璺戠粨鏋?
璇存槑锛氬綋鍓嶄粨搴撲腑鐨?`S001_R/S002_R/S003_R` 鏄凡鏈夋牱鏈暟鎹紝鍙敤浜庤瘯璺戞祦绋嬶紱瀹冧滑涓嶇瓑鍚屼簬浣犳鍦ㄧ瓑寰呭悎浣滆€呭彂閫佺殑鍘熷鐪熷疄鏁版嵁銆?
2026-07-07 浣跨敤褰撳墠浠ｇ爜鎵归噺璇曡窇 3 涓牱鏈?x 5 涓尯鍩燂紝鎵€鏈夊尯鍩熼兘鑳芥墽琛屽埌缁撴灉锛屾病鏈夊紓甯镐腑鏂€?
| sample_id | region_id | patch_faces | template_points | unmapped | flipped | degenerate | status |
|---|---:|---:|---:|---:|---:|---:|---|
| S001_R | T001 | 62 | 45 | 22 | 62 | 0 | WARNING |
| S001_R | T002 | 619 | 45 | 0 | 0 | 0 | PASS |
| S001_R | T003 | 117 | 45 | 6 | 117 | 0 | WARNING |
| S001_R | T004 | 506 | 45 | 7 | 506 | 0 | WARNING |
| S001_R | T005 | 1004 | 45 | 2 | 0 | 0 | WARNING |
| S002_R | T001 | 12482 | 45 | 20 | 4336 | 2 | WARNING |
| S002_R | T002 | 418 | 45 | 1 | 0 | 0 | WARNING |
| S002_R | T003 | 29 | 45 | 15 | 29 | 0 | WARNING |
| S002_R | T004 | 662 | 45 | 2 | 662 | 0 | WARNING |
| S002_R | T005 | 1158 | 45 | 1 | 0 | 0 | WARNING |
| S003_R | T001 | 91 | 45 | 15 | 91 | 0 | WARNING |
| S003_R | T002 | 738 | 45 | 0 | 0 | 0 | PASS |
| S003_R | T003 | 33 | 45 | 15 | 33 | 0 | WARNING |
| S003_R | T004 | 532 | 45 | 3 | 532 | 0 | WARNING |
| S003_R | T005 | 1639 | 45 | 0 | 0 | 0 | PASS |

缁熻锛?
```text
PASS: 3
WARNING: 12
FAIL: 0
```

## 7. 濡備綍鍒ゆ柇涓€涓?region 鏄惁鑳借繘鍏ュ悗缁?PCA

涓存椂寤鸿锛?
| 鏉′欢 | 鍒ゆ柇 |
|---|---|
| `unmapped == 0` | 鍙互璁や负 2D 妯℃澘鐐瑰叏閮ㄦ垚鍔熸槧灏勫洖 3D |
| `degenerate == 0` | UV 鍙傛暟鍖栨病鏈夐€€鍖栦笁瑙掗潰 |
| `patch_faces` 鏄庢樉灏忎簬鏁磋€虫€婚潰鏁?| patch 鎻愬彇澶ф鐜囨槸灞€閮ㄥ尯鍩?|
| `patch_faces` 鎺ヨ繎鏁磋€虫€婚潰鏁?| 杈圭晫娌℃湁鎴愬姛鍒囧嚭灞€閮?patch锛岄渶瑕佹鏌?landmark 鎴栬矾寰?|
| `unmapped > 0` | 鏆傛椂涓嶈杩涘叆 PCA锛岄渶瑕佽皟鏁村尯鍩熸垨杈圭晫绛栫暐 |

褰撳墠鍙洿鎺ヨ涓哄共鍑€閫氳繃鐨勭粍鍚堬細

```text
S001_R T002
S003_R T002
S003_R T005
```

褰撳墠涓嶅缓璁洿鎺ヨ繘鍏?PCA 鐨勭粍鍚堬細

```text
鍏朵粬鎵€鏈?WARNING 鍖哄煙
```

## 8. 涓轰粈涔堟湁浜涘尯鍩熸槸 WARNING

涓昏鍘熷洜涓嶆槸浠ｇ爜宕╂簝锛岃€屾槸灞€閮ㄤ笁瑙掑尯鍩熺殑鍑犱綍杈圭晫杩樹笉澶熺悊鎯炽€?
甯歌鎯呭喌锛?
1. 涓夋潯 landmark 鏈€鐭矾寰勫彂鐢熼噸鍙犳垨浜ゅ弶锛屽鑷磋竟鐣屼笉鏄竴涓共鍑€鐨勭畝鍗曢棴鍚堜笁瑙掔幆銆?2. 杈圭晫鍒囧垎鍑虹殑 patch 澶皬銆佸お绐勬垨鍖呭惈 UV 鎶樺彔锛屾爣鍑嗕笁瑙掑煙涓殑閮ㄥ垎妯℃澘鐐规壘涓嶅埌瀵瑰簲婧愰潰鐗囥€?3. 鏌愪簺鍖哄煙鐨勮竟鐣屾病鏈夌湡姝ｅ垏寮€ mesh face graph锛屼緥濡?`S002_R T001` 鐨?`patch_faces=12482`锛屾帴杩戞暣鑰虫€婚潰鏁般€?4. 婧?mesh face winding 涓庢爣鍑嗕笁瑙掓柟鍚戠浉鍙嶏紝瀵艰嚧 `flipped` 寰堥珮銆傝繖涓寚鏍囬渶瑕佺粨鍚?`unmapped` 鍜屽疄闄呭彲瑙嗗寲鍒ゆ柇锛屼笉鑳藉崟鐙綔涓哄け璐ヤ緷鎹€?
## 9. 鍚堜綔鑰呯湡瀹炴暟鎹埌浣嶅悗鐨勪娇鐢ㄦ祦绋?
寤鸿鎸変笅闈㈡楠ゅ仛绗竴娆℃帴鍏ワ細

1. 灏?mesh 鏀惧叆锛?
```text
data/clean_mesh/<sample_id>_<side>.ply
```

渚嬪锛?
```text
data/clean_mesh/A001_R.ply
```

2. 灏?landmark CSV 鏀惧叆锛?
```text
data/landmarks/<sample_id>_<side>_landmarks.csv
```

渚嬪锛?
```text
data/landmarks/A001_R_landmarks.csv
```

3. 纭 landmark CSV 鑷冲皯鏈夎繖浜涘垪锛?
```text
landmark_id,x,y,z
```

4. 纭 `config/region_table.csv` 涓娇鐢ㄧ殑 landmark 閮藉瓨鍦ㄤ簬璇ユ牱鏈殑 landmark CSV銆?
5. 鐢ㄧ 4 鑺傜殑鏈€灏忕ず渚嬫浛鎹細

```python
sample_id = "A001_R"
```

6. 鍏堝彧鐪?QC 鎽樿锛屼笉鎬ョ潃杩涘叆 PCA銆?
7. 鍙湁婊¤冻浠ヤ笅鏉′欢鐨?region 鎵嶄綔涓?W2 鍚堟牸杈撳嚭锛?
```text
unmapped == 0
degenerate == 0
patch_faces 涓嶆槸鏁磋€崇骇鍒?```

## 10. 鐩墠杩樻病鏈夊仛鐨勪簨

浠ヤ笅鍐呭杩樻病鏈夋帴鍏ワ紝寤鸿浣滀负涓嬩竴姝ワ細

1. 灏?`build_region_remesh` 鎺ュ叆鍛戒护琛岃剼鏈紝褰㈡垚姝ｅ紡 `scripts/remesh_ear.py`銆?2. 杈撳嚭姣忎釜 region 鐨?remesh patch PLY/OBJ銆?3. 杈撳嚭姣忎釜鏍锋湰鐨?remesh points CSV 鍜?remesh QC CSV銆?4. 澧炲姞杈圭晫璺緞鑷氦/閲嶅彔妫€娴嬨€?5. 澧炲姞 patch 鍙鍖栵紝甯姪浜哄伐鍒ゆ柇閫夊尯鏄惁姝ｇ‘銆?6. 鍦ㄧ湡瀹炴暟鎹笂纭 landmark 瀹氫箟鍜?`region_table.csv` 鏄惁闇€瑕侀噸鐢汇€?
## 11. 褰撳墠缁撹

鐩墠浠ｇ爜灞傞潰宸茬粡鍙互鍦ㄧ幇鏈夋牱鏈暟鎹笂璺戦€?W2 闃舵 1 鍒伴樁娈?8銆?
浣嗕粠 QC 鐪嬶紝瀹冭繕涓嶈兘琚涓哄凡缁忚揪鍒扳€滄墍鏈夊尯鍩熷彲鐩存帴杩涘叆 W3/PCA鈥濈殑璐ㄩ噺銆傚綋鍓嶆渶鍏抽敭鐨勪笅涓€姝ヤ笉鏄户缁啓 PCA锛岃€屾槸鍏堟妸 W2 鐨?region 杈圭晫璐ㄩ噺鎺у埗鍋氬ソ锛屽挨鍏舵槸锛?
- 妫€鏌ヤ笁鏉?boundary paths 鏄惁褰㈡垚绠€鍗曢棴鍚堢幆銆?- 瀵?`unmapped > 0` 鐨勫尯鍩熻繘琛屽彲瑙嗗寲璇婃柇銆?- 蹇呰鏃惰皟鏁?region landmark 缁勫悎锛屾垨澧炲姞鎵嬪伐鎸囧畾/绾︽潫杈圭晫璺緞鐨勮兘鍔涖€?

