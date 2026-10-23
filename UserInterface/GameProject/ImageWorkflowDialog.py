"""Explicit image OCR, region correction and preview approval workflow."""
from __future__ import annotations
import json
from pathlib import Path
from PyQt5.QtCore import Qt,QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
    QComboBox,QLineEdit,QPlainTextEdit,QFileDialog,QSplitter,QWidget)
from .GameProjectPage import _GameProjectJob
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.JobControl import request_action


class ImageWorkflowDialog(QDialog):
    def __init__(self,project,parent=None):
        super().__init__(parent);self.project=project;self.worker=None;self.items={};self.candidate=None
        self._job_id='';self._control_store=None
        self._poll=QTimer(self);self._poll.setInterval(150);self._poll.timeout.connect(self._poll_control)
        self.setWindowTitle('图片文字：识别、校正与输出预览');self.resize(1160,850)
        layout=QVBoxLayout(self)
        note=QLabel('按顺序完成：选择图片 → OCR 或填写区域 → 确认区域 → 提交译文 → 选择干净底图和字体 → 生成预览 → 目视批准。\n译文可在主页面编辑。OCR 候选需要校正；底图只允许修改区域内部。PNG / MV、MZ 加密 PNG 可处理。')
        note.setWordWrap(True);layout.addWidget(note)
        self.files=QComboBox();self.files.currentTextChanged.connect(self._selected);layout.addWidget(self.files)
        form=QFormLayout();self.exe=QLineEdit();self.tessdata=QLineEdit();self.language=QLineEdit('jpn+eng')
        for label,field,folder in [('Tesseract 程序',self.exe,False),('tessdata 目录',self.tessdata,True)]:
            row=QHBoxLayout();row.addWidget(field);button=QPushButton('选择');row.addWidget(button)
            button.clicked.connect(lambda _=False,f=field,d=folder:self._choose(f,d));form.addRow(label,row)
        form.addRow('OCR 语言',self.language);layout.addLayout(form)
        configure=QPushButton('OCR 工具：一键下载配置 / 选择已有安装')
        configure.clicked.connect(self._configure_ocr);layout.addWidget(configure)
        self._fill_ocr()
        top=QHBoxLayout();self.buttons=[]
        for text,action in [('查看原图','preview'),('本地 OCR','ocr'),('确认区域','regions')]:
            button=QPushButton(text);button.clicked.connect(lambda _=False,a=action:self.run(a));top.addWidget(button);self.buttons.append(button)
        layout.addLayout(top)
        splitter=QSplitter();self.preview_label=QLabel('图片预览');self.preview_label.setAlignment(Qt.AlignCenter)
        self.regions=QPlainTextEdit();self.regions.setPlaceholderText('[{"box":[x,y,w,h],"text":"校正后的原文","font_size":24,"color":[255,255,255,255],"align":"center"}]')
        splitter.addWidget(self.preview_label);splitter.addWidget(self.regions);layout.addWidget(splitter,1)
        self.clean=QLineEdit();self.font=QLineEdit();base_form=QFormLayout()
        for text,field in [('已擦字底图 PNG',self.clean),('中文字体 TTF/OTF',self.font)]:
            row=QHBoxLayout();row.addWidget(field);button=QPushButton('选择');row.addWidget(button)
            button.clicked.connect(lambda _=False,f=field:self._choose(f,False));base_form.addRow(text,row)
        layout.addLayout(base_form)
        bottom=QHBoxLayout()
        for text,action in [('保存底图与字体','base'),('生成翻译预览','render'),('目视确认并批准此预览','approve')]:
            button=QPushButton(text);button.clicked.connect(lambda _=False,a=action:self.run(a));bottom.addWidget(button);self.buttons.append(button)
        layout.addLayout(bottom)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        controls=QHBoxLayout();self.pause_button=QPushButton('暂停 OCR')
        self.continue_button=QPushButton('继续 OCR');self.cancel_button=QPushButton('取消 OCR')
        for button,action in ((self.pause_button,'pause'),(self.continue_button,'resume'),(self.cancel_button,'cancel')):
            button.clicked.connect(lambda _=False,a=action:self._control(a));button.setEnabled(False);controls.addWidget(button)
        layout.addLayout(controls)
        self.close_button=QPushButton('返回译文表');self.close_button.clicked.connect(self.accept);layout.addWidget(self.close_button)
        QTimer.singleShot(0,lambda:self.run('inventory'))

    def _choose(self,field,directory):
        path=QFileDialog.getExistingDirectory(self,'选择目录') if directory else QFileDialog.getOpenFileName(self,'选择文件')[0]
        if path:field.setText(path)

    def _fill_ocr(self):
        from ModuleFolders.Service.GameProject.ExternalTools import ExternalTools
        status=ExternalTools().status('ocr')
        if status['ready']:
            self.exe.setText(str(Path(status['path'])/'tesseract.exe'))
            self.tessdata.setText(str(Path(status['path'])/'tessdata'))

    def _configure_ocr(self):
        from .ExternalToolsDialog import ExternalToolsDialog
        ExternalToolsDialog(self,'ocr').exec_();self._fill_ocr()

    def _selected(self,rel):
        self.candidate=None;self.preview_label.clear()
        entry=self.settings.get(rel,{}) if hasattr(self,'settings') else {}
        self.regions.setPlainText(json.dumps(entry.get('regions',[]),ensure_ascii=False,indent=2))

    def run(self,action):
        if self.worker:return
        if action=='ocr' and (not Path(self.exe.text()).is_file() or not Path(self.tessdata.text()).is_dir()):
            self._configure_ocr()
            if not self.exe.text():return
        rel=self.files.currentText();p={'project':self.project,'action':action,'relative_path':rel}
        try:
            if action=='ocr':p.update(executable=self.exe.text(),tessdata=self.tessdata.text(),language=self.language.text())
            elif action=='regions':
                p.update(source_sha256=self.items[rel]['source_sha256'],regions=json.loads(self.regions.toPlainText()))
            elif action=='base':p.update(clean_base=self.clean.text(),font=self.font.text())
            elif action=='approve':
                if not self.candidate or self.candidate.get('relative_path')!=rel:raise ValueError('请先生成并查看当前图片的翻译预览')
                p['sha256']=self.candidate['sha256']
            elif action!='inventory' and rel not in self.items:raise ValueError('请选择支持的图片')
        except Exception as exc:self.status.setText(str(exc));return
        self.status.setText('正在处理…');self._enabled(False)
        self.worker=_GameProjectJob('image',p,self)
        self.worker.succeeded.connect(self._success);self.worker.failed.connect(self.status.setText)
        self.worker.jobStarted.connect(self._job_started)
        self.worker.finished.connect(self._finished);self.worker.start()

    def _success(self,payload):
        if payload.get('operation')=='cancelled':
            self.status.setText('OCR 已取消；原有文字和区域保留。可重新识别。');return
        action=payload['action'];r=payload['result']
        if action=='inventory':
            self.settings=r['settings'];self.items={i['relative_path']:i for i in r['images'] if i['supported']}
            self.files.addItems(sorted(self.items));self.status.setText(f'可处理图片：{len(self.items)}')
        elif action=='ocr':
            rows=[{'box':i['box'],'text':i['text'],'font_size':24,'color':[255,255,255,255],'align':'center'} for i in r['regions']]
            self.regions.setPlainText(json.dumps(rows,ensure_ascii=False,indent=2))
            self.status.setText(f"候选 {len(rows)} 个；请校正文字和区域后点击确认。原始置信度记录：{r['candidate_file']}")
        elif action in ('preview','render'):
            pixmap=QPixmap(r['preview']);self.preview_label.setPixmap(pixmap.scaled(520,420,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            if action=='render':self.candidate=r
            self.status.setText(('预览已生成，须目视批准。' if action=='render' else '原图已解码。')+' 文件：'+r['preview'])
        elif action=='regions':
            rel=self.files.currentText()
            self.settings.setdefault(rel,{})['regions']=r['regions']
            self.regions.setPlainText(json.dumps(r['regions'],ensure_ascii=False,indent=2))
            self.candidate=None
            self.status.setText('区域已确认。返回主页面为图片单元填写译文，再进入此窗口生成预览。')
        elif action=='base':self.status.setText('底图和字体已捕获；可生成预览。')
        else:self.status.setText('此预览已批准；修改译文、区域或样式后需要重新生成并批准。')

    def _enabled(self,value):
        self.files.setEnabled(value);self.close_button.setEnabled(value)
        for button in self.buttons:button.setEnabled(value)

    def _finished(self):
        self._poll.stop();self._job_id=''
        if self._control_store:self._control_store.close();self._control_store=None
        self._poll_control()
        worker=self.worker;self.worker=None;worker.deleteLater();self._enabled(True)

    def _job_started(self,payload):
        self._job_id=payload['job_id'];self._control_store=ProjectStore(payload['project_root'])
        self._poll.start();self._poll_control()

    def _poll_control(self):
        state=''
        if self._control_store and self._job_id:
            job=next((j for j in self._control_store.jobs() if j['job_id']==self._job_id),None)
            if job:state=job['run_state']
        self.pause_button.setEnabled(state=='RUNNING')
        self.continue_button.setEnabled(state=='PAUSED')
        self.cancel_button.setEnabled(state in {'RUNNING','PAUSED','PAUSE_REQUESTED'})
        detail={'PAUSE_REQUESTED':'正在等待本次识别结束，再暂停保存候选。',
            'PAUSED':'OCR 已暂停；继续后保存候选，也可取消。',
            'CANCEL_REQUESTED':'正在停止 OCR…','COMMITTING':'正在保存 OCR 候选…'}
        if state in detail:self.status.setText(detail[state])

    def _control(self,action):
        if not self._control_store or not self._job_id:return
        try:request_action(self._control_store,self._job_id,action);self._poll_control()
        except Exception as error:self.status.setText('控制请求未生效：'+str(error))

    def done(self,result):
        if self.worker:self.status.setText('请等待当前图片操作完成后关闭。');return
        super().done(result)

    def closeEvent(self,event):
        if self.worker:event.ignore();return
        super().closeEvent(event)
