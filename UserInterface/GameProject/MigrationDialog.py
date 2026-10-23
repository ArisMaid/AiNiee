"""Review five-way reconciliation before applying reliable old translations."""
import json
from PyQt5.QtCore import Qt,QAbstractTableModel,QModelIndex,QThread,pyqtSignal,QTimer
from PyQt5.QtWidgets import (QAbstractItemView,QCheckBox,QComboBox,QDialog,QFileDialog,
    QApplication,QFormLayout,QHBoxLayout,QInputDialog,QLabel,QLineEdit,QPlainTextEdit,QPushButton,QSplitter,QTableView,QVBoxLayout)

from ModuleFolders.Service.GameProject.MigrationWorkflow import prepare_review,apply_review,resume_review,load_review,reconciliation_rows
from ModuleFolders.Service.GameProject.ProjectStore import ProjectStore
from ModuleFolders.Service.GameProject.JobControl import request_action

_LABELS={'reused':'复用','new':'新增','modified':'修改','orphaned':'孤立','conflict':'冲突'}


class _ReconciliationModel(QAbstractTableModel):
    def __init__(self,parent=None):super().__init__(parent);self.rows=[]
    def set_rows(self,rows):self.beginResetModel();self.rows=list(rows);self.endResetModel()
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else 4
    def headerData(self,section,orientation,role=Qt.DisplayRole):
        if orientation==Qt.Horizontal and role==Qt.DisplayRole:return ('类别','旧单元','目标单元','判断依据')[section]
    def flags(self,index):return Qt.ItemIsEnabled|Qt.ItemIsSelectable
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()]
        if role==Qt.UserRole:return row.get('new_unit_id','')
        if role not in (Qt.DisplayRole,Qt.ToolTipRole):return None
        return (_LABELS[row['category']],row.get('old_unit_id',''),row.get('new_unit_id',''),row['explanation'])[index.column()]


class _MigrationWorker(QThread):
    succeeded=pyqtSignal(dict);failed=pyqtSignal(str)
    jobStarted=pyqtSignal(str);progressed=pyqtSignal(int,int,str)
    def __init__(self,operation,payload,parent=None):super().__init__(parent);self.operation=operation;self.payload=payload
    def run(self):
        try:
            if self.operation=='plan':
                result=prepare_review(self.payload['old'],self.payload['new'],self.payload['confirm'])
            elif self.operation=='resume':result=resume_review(self.payload['new'],self.payload['job_id'],
                progress=self.progressed.emit,on_job=self.jobStarted.emit)
            else:result=apply_review(self.payload['new'],self.payload['plan_id'],
                progress=self.progressed.emit,on_job=self.jobStarted.emit)
            self.succeeded.emit({'operation':self.operation,'result':result})
        except Exception as error:self.failed.emit(f'{type(error).__name__}: {error}')


class MigrationDialog(QDialog):
    def __init__(self,project_root,parent=None):
        from ModuleFolders.Infrastructure.Platform.QtBootstrap import configure_qt_fonts
        configure_qt_fonts(QApplication.instance())
        super().__init__(parent);self.project_root=str(project_root);self._worker=None;self.envelope=None
        self.changed=False;self.selected_target='';self._applied=False;self._job_id='';self._control_store=None
        self._poll=QTimer(self);self._poll.setInterval(250);self._poll.timeout.connect(self._poll_control)
        self.setWindowTitle('迁移旧译文');self.resize(1160,800)
        layout=QVBoxLayout(self);form=QFormLayout()
        self.old_edit=QLineEdit();self.browse_button=QPushButton('选择旧工程')
        row=QHBoxLayout();row.addWidget(self.old_edit);row.addWidget(self.browse_button)
        self.browse_button.clicked.connect(self._choose_old);form.addRow('旧工程',row)
        target=QLineEdit(self.project_root);target.setReadOnly(True);form.addRow('目标工程',target)
        self.confirm_box=QCheckBox('为缺少 game_id 的工程建立明确关联：我确认两者属于同一游戏')
        form.addRow(self.confirm_box);layout.addLayout(form)
        note=QLabel('先生成对账，再应用可靠匹配。已有有效译文、手动锁定及其余四类条目保持原样。'
            '关联绑定两份工程及来源清单，不能覆盖已知的游戏 ID 冲突。')
        note.setWordWrap(True);layout.addWidget(note)
        buttons=QHBoxLayout();self.plan_button=QPushButton('生成对账');self.apply_button=QPushButton('应用可靠匹配')
        self.plan_button.clicked.connect(self._plan);self.apply_button.clicked.connect(self._apply)
        buttons.addWidget(self.plan_button);buttons.addWidget(self.apply_button)
        self.filter_box=QComboBox();self.filter_box.addItem('全部','all')
        for key,label in _LABELS.items():self.filter_box.addItem(label,key)
        buttons.addWidget(self.filter_box);layout.addLayout(buttons)
        self.summary_label=QLabel('尚未生成对账');self.summary_label.setWordWrap(True);layout.addWidget(self.summary_label)
        splitter=QSplitter(Qt.Vertical);self.model=_ReconciliationModel(self);self.table=QTableView()
        self.table.setModel(self.model);self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False);self.table.verticalHeader().setVisible(False)
        for column,width in ((0,80),(1,280),(2,280)):self.table.setColumnWidth(column,width)
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table);self.detail=QPlainTextEdit();self.detail.setReadOnly(True);splitter.addWidget(self.detail)
        splitter.setStretchFactor(0,3);splitter.setStretchFactor(1,2);layout.addWidget(splitter,1)
        locate=QPushButton('在目标工程定位所选单元');locate.clicked.connect(self._locate);layout.addWidget(locate)
        self.status_label=QLabel('');self.status_label.setWordWrap(True);layout.addWidget(self.status_label)
        controls=QHBoxLayout();self.pause_button=QPushButton('暂停');self.continue_button=QPushButton('继续')
        self.cancel_button=QPushButton('取消');self.recover_button=QPushButton('恢复未完成的迁移…')
        for button,action in ((self.pause_button,'pause'),(self.continue_button,'resume'),(self.cancel_button,'cancel')):
            button.clicked.connect(lambda checked=False,value=action:self._control(value));controls.addWidget(button)
        self.recover_button.clicked.connect(self._recover);controls.addWidget(self.recover_button);layout.addLayout(controls)
        self.control_label=QLabel('取消会保留已提交译文；恢复时先核对来源及尚未提交的条目。')
        self.control_label.setWordWrap(True);layout.addWidget(self.control_label)
        close=QPushButton('关闭');close.clicked.connect(self.close);layout.addWidget(close)
        self.old_edit.textChanged.connect(self._reset);self.confirm_box.toggled.connect(self._reset)
        self.filter_box.currentIndexChanged.connect(self._filter)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self._update_enabled()

    def is_busy(self):return self._worker is not None

    def _choose_old(self):
        path=QFileDialog.getExistingDirectory(self,'选择旧工程目录',self.old_edit.text())
        if path:self.old_edit.setText(path)

    def _reset(self,*args):
        self.envelope=None;self._applied=False;self.model.set_rows([]);self.detail.clear()
        self.summary_label.setText('尚未生成对账');self._update_enabled()

    def _plan(self):
        self._reset()
        self._start('plan',{'old':self.old_edit.text().strip(),'new':self.project_root,'confirm':self.confirm_box.isChecked()})

    def _apply(self):
        if self.envelope:self._start('apply',{'new':self.project_root,'plan_id':self.envelope['plan_id']})

    def _start(self,operation,payload):
        if self.is_busy():return
        worker=_MigrationWorker(operation,payload,self);self._worker=worker
        worker.succeeded.connect(self._done);worker.failed.connect(self._failed);worker.finished.connect(self._finished)
        worker.jobStarted.connect(self._job_started);worker.progressed.connect(self._progressed)
        worker.start();self._update_enabled();self.status_label.setText('正在生成对账…' if operation=='plan' else '正在应用可靠匹配…')

    def _done(self,payload):
        result=payload['result']
        if payload['operation']=='plan':
            self.envelope=result;self._applied=False;self._filter()
            counts=result['plan']['stats']['reconciliation_counts'];identity=result['plan']['identity']
            method='人工关联' if identity.get('verification_method')=='explicit_lineage' else '游戏 ID'
            state=('身份已验证：'+method) if identity['verified'] else '身份未验证：需要明确的工程关联'
            self.summary_label.setText(state+'；'+'，'.join(f'{label} {counts[key]}' for key,label in _LABELS.items()))
            self.status_label.setText('对账已保存。核对条目后再应用可靠匹配。')
        else:
            self.changed=True;self._applied=True
            self.status_label.setText(f"已复用 {result['accepted']} 条；拒绝 {result['rejected']} 条。对账表保留操作前的快照。")
            self.control_label.setText(f"历史已提交 {result.get('reused_units',0)} 条；本次新增 {result.get('new_units',result['accepted'])} 条。"
                '历史条目之后的人工编辑和锁定以目标工程当前值为准。')

    def _failed(self,message):
        if self._job_id:self._applied=True
        self.status_label.setText('未完成：'+message+'；已提交译文保留，可恢复任务或重新生成对账。')

    def _job_started(self,job_id):
        self._job_id=job_id;self.changed=True
        if self._control_store is None:self._control_store=ProjectStore(self.project_root)
        self._poll.start();self._poll_control()

    def _progressed(self,done,total,detail):
        self.control_label.setText(f'已核对/提交 {done}/{total} 条。暂停和取消在当前单元提交边界生效。')

    def _poll_control(self):
        state=''
        if self._control_store and self._job_id:
            job=next((j for j in self._control_store.jobs() if j['job_id']==self._job_id),None)
            if job:state=job['run_state']
        self.pause_button.setEnabled(state=='RUNNING')
        self.continue_button.setEnabled(state=='PAUSED')
        self.cancel_button.setEnabled(state in {'RUNNING','PAUSED','PAUSE_REQUESTED'})
        if state in {'PAUSED','PAUSE_REQUESTED','CANCEL_REQUESTED','COMMITTING'}:
            text={'PAUSED':'已暂停；已提交译文已保存。','PAUSE_REQUESTED':'正在等待当前单元到达暂停边界…',
                'CANCEL_REQUESTED':'正在停止；已提交译文会保留。','COMMITTING':'正在保存迁移结果…'}[state]
            self.control_label.setText(text)

    def _control(self,action):
        if not self._control_store or not self._job_id:return
        try:request_action(self._control_store,self._job_id,action);self._poll_control()
        except Exception as error:self.status_label.setText('控制请求未生效：'+str(error))

    def _recover(self):
        if self.is_busy():return
        try:
            with ProjectStore(self.project_root) as store:
                jobs=[j for j in store.jobs() if j['operation']=='MIGRATE' and
                    j['run_state'] in {'CANCELLED','FAILED','INTERRUPTED','RUNNING','PAUSED','PAUSE_REQUESTED','CANCEL_REQUESTED','COMMITTING','QUEUED'}
                    and j['payload'].get('algorithm')=='migration-accepted-receipts-v1']
                registry=store.metadata().get('migration_reviews',{})
                jobs=[j for j in jobs if registry.get(j['payload'].get('plan_id'),{}).get('state')=='planned']
            if not jobs:self.status_label.setText('没有可恢复的迁移任务。');return
            labels=[f"{j['job_id']} · {j['run_state']} · 已记录 {j['checkpoint']} 条" for j in reversed(jobs)]
            selected,ok=QInputDialog.getItem(self,'恢复迁移','选择一次未完成的尝试',labels,0,False)
            if ok:self._resume_job(selected.split()[0])
        except Exception as error:self._failed(str(error))

    def _resume_job(self,job_id):
        if self.is_busy():return
        try:
            with ProjectStore(self.project_root) as store:job=next(j for j in store.jobs() if j['job_id']==job_id)
            envelope=load_review(self.project_root,job['payload']['plan_id'])
            self.old_edit.setText(envelope['binding']['old_root'])
            self._done({'operation':'plan','result':envelope})
            self._start('resume',{'new':self.project_root,'job_id':job_id})
        except Exception as error:self._failed(str(error))

    def _finished(self):
        worker=self.sender()
        if worker is self._worker:
            self._worker=None;self._poll.stop()
            if self._control_store:self._control_store.close();self._control_store=None
            self._job_id='';self._poll_control()
        worker.deleteLater();self._update_enabled()

    def _filter(self,*args):
        self.model.set_rows(reconciliation_rows(self.envelope,self.filter_box.currentData()) if self.envelope else [])
        self.detail.clear()

    def _selected(self,index,*args):
        if not self.envelope or not index.isValid() or not 0<=index.row()<len(self.model.rows):return
        row=self.model.rows[index.row()];parts=[_LABELS[row['category']]+'：'+row['explanation']]
        for side,key,label in (('old','old_unit_id','旧工程（对账时）'),('new','new_unit_id','目标工程（对账时）')):
            uid=row.get(key,'');detail=self.envelope['details'][side].get(uid)
            if not detail:continue
            parts.append(label+'\n单元：'+uid+'\n原文：'+detail['source']+'\n译文：'+(detail['translation'] or '（无）')
                +'\n位置：'+json.dumps(detail['locations'],ensure_ascii=False,indent=2))
        self.detail.setPlainText('\n\n'.join(parts))

    def _locate(self):
        if self.is_busy():return
        index=self.table.currentIndex()
        if index.isValid():
            uid=self.model.data(index,Qt.UserRole)
            if uid:self.selected_target=uid;self.accept()

    def _update_enabled(self):
        busy=self.is_busy();self.old_edit.setEnabled(not busy);self.confirm_box.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.recover_button.setEnabled(not busy)
        if not busy:
            for button in (self.pause_button,self.continue_button,self.cancel_button):button.setEnabled(False)
        self.plan_button.setEnabled(not busy and bool(self.old_edit.text().strip()))
        can_apply=bool(self.envelope and self.envelope['plan']['identity']['verified'] and self.envelope['plan']['matches'])
        self.apply_button.setEnabled(not busy and not self._applied and can_apply)

    def closeEvent(self,event):
        if self.is_busy():self.status_label.setText('正在完成当前操作，请稍候');event.ignore()
        else:super().closeEvent(event)

    def accept(self):
        if not self.is_busy():super().accept()

    def reject(self):
        if not self.is_busy():super().reject()
