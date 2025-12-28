# pdf-bookmark-edit
python qt6 gui. 通过调用cpdf来实现给pdf添加或者编辑目录的功能，有实时预览功能
   1. 双页面设计：编辑页与实时预览页分离。
   2. 灵活解析：支持层级缩进、页码偏移，并能自动处理全角字符。
   3. PDF 预览：内置 Chromium 内核预览器，可直接检验目录跳转。
   4. cpdf 集成：高效完成 PDF 目录的写入。
在archlinux下测试通过，其他系统(linux发行版，windows, mac）只要安装cpdf理论上也能运行
