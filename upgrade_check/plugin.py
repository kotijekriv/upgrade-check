"""QGIS UI and public-index transport. GPL-3.0-or-later, Copyright 2026 Attempts."""
from pathlib import Path
from datetime import datetime, timezone

from qgis.PyQt.QtCore import QObject, QTimer, QUrl, Qt, QStandardPaths, pyqtSignal
from qgis.PyQt.QtGui import QColor, QDesktopServices, QIcon
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QAction, QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
)
from qgis.core import Qgis, QgsApplication, QgsNetworkAccessManager, QgsSettings
import qgis.utils

from .core import (Installed, MAX_INDEX_BYTES, STATUSES, compare, html_report,
                   index_url, json_report, make_report, parse_index,
                   plain_report, target_version)


def current_version():
    return Qgis.QGIS_VERSION.split('-')[0]


def installed_plugins():
    """Read metadata only. Never import or enable an installed plugin."""
    qgis.utils.updateAvailablePlugins()
    settings = QgsSettings()
    settings.beginGroup('PythonPlugins')
    saved = {key for key in settings.childKeys() if not key.startswith('watchDog')}
    settings.endGroup()
    available = set(qgis.utils.available_plugins)
    bundled_path = (Path(QgsApplication.pkgDataPath())/'python/plugins').resolve()
    result = []
    for package in sorted(available | saved):
        if package not in available:
            result.append(Installed(package, package, present=False))
            continue
        try:
            origin = next((Path(p)/package/'metadata.txt' for p in qgis.utils.plugin_paths
                           if (Path(p)/package/'metadata.txt').is_file()), None)
            bundled = bool(origin and bundled_path in origin.resolve().parents)
            def value(key):
                text = qgis.utils.pluginMetadata(package,key)
                return '' if text in (None,'__error__') else str(text)
            result.append(Installed(package, value('name') or package, value('version'),
                                    value('qgisMinimumVersion'), value('qgisMaximumVersion'), bundled))
        except (OSError, ValueError, RuntimeError):
            result.append(Installed(package, package, error='unreadable metadata'))
    return result


class IndexFetcher(QObject):
    complete = pyqtSignal(object, str)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)

    def start(self, current, target):
        self.urls = list(dict.fromkeys([index_url(current),index_url(target)]))
        self.indexes = {}
        self.cancelled = False
        self._next()

    def cancel(self):
        self.cancelled = True
        self.timer.stop()
        if self.reply is not None:
            self.reply.abort()

    def _timeout(self):
        self.abort_reason = 'Repository request timed out. Check your connection and try again.'
        if self.reply is not None:
            self.reply.abort()

    def _next(self):
        if not self.urls:
            self.complete.emit(self.indexes, datetime.now(timezone.utc).isoformat())
            return
        self.url = self.urls.pop(0)
        self.progress.emit('Fetching official index for QGIS '+self.url.split('=')[-1]+'…')
        self.buffer = bytearray()
        self.abort_reason = ''
        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b'User-Agent',b'UpgradeCheck/0.1.0 (QGIS)')
        request.setAttribute(QNetworkRequest.CacheLoadControlAttribute,QNetworkRequest.AlwaysNetwork)
        self.reply = QgsNetworkAccessManager.instance().get(request)
        reply = self.reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finished(reply))
        self.timer.start(30000)

    def _read(self, reply):
        if reply is not self.reply:
            return
        self.buffer.extend(bytes(reply.readAll()))
        if len(self.buffer) > MAX_INDEX_BYTES:
            self.abort_reason = 'Repository response exceeded the 20 MiB limit.'
            reply.abort()

    def _finished(self, reply):
        if reply is not self.reply:
            reply.deleteLater()
            return
        self.timer.stop()
        self._read(reply)
        self.reply = None
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        network_error = reply.error() != QNetworkReply.NoError
        error_text = reply.errorString()
        final_url = reply.url()
        reply.deleteLater()
        if self.cancelled:
            self.failed.emit('Check cancelled. No new report was produced.')
            return
        if self.abort_reason or network_error or status != 200:
            self.failed.emit(self.abort_reason or f'Could not read the official repository ({status or error_text}). No compatibility conclusion was made.')
            return
        if final_url.scheme() != 'https' or final_url.host() != 'plugins.qgis.org':
            self.failed.emit('Unexpected repository redirect. No compatibility conclusion was made.')
            return
        try:
            self.indexes[self.url] = parse_index(bytes(self.buffer))
        except Exception as error:
            # Keep parse failures visible, including malformed XML, not empty data.
            self.failed.emit('Could not read repository data: '+str(error))
            return
        self._next()


class CheckDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.setWindowTitle('Upgrade Check')
        self.resize(1080,720)
        self.report = None
        self.busy = False
        self.last_export_dir = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        self.fetcher = IndexFetcher(self)
        self.fetcher.progress.connect(self._message)
        self.fetcher.complete.connect(self._complete)
        self.fetcher.failed.connect(self._failed)
        layout = QVBoxLayout(self)
        title = QLabel('<h2>Check your plugins before upgrading</h2>')
        layout.addWidget(title)
        intro = QLabel('A read-only report of official repository declarations. It does not test plugin behaviour or change your installation.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('Target QGIS:'))
        self.target = QComboBox()
        self.target.setObjectName('targetVersion')
        self.target.setEditable(True)
        self.target.addItems(['4.2','4.0','4.4'])
        self.target.setToolTip('Choose the exact major.minor version you plan to use. Future-version listings do not establish that QGIS itself has been released.')
        controls.addWidget(self.target)
        controls.addWidget(QLabel('Current: '+current_version()))
        controls.addStretch()
        self.check = QPushButton('Check this profile')
        self.check.setObjectName('checkProfile')
        self.check.clicked.connect(self.start)
        controls.addWidget(self.check)
        self.cancel = QPushButton('Cancel')
        self.cancel.clicked.connect(self.fetcher.cancel)
        self.cancel.setVisible(False)
        controls.addWidget(self.cancel)
        layout.addLayout(controls)
        self.message = QLabel('Only QGIS version numbers are sent to plugins.qgis.org. Your plugin list stays on this device.')
        self.message.setObjectName('checkStatus')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0,0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.table = QTableWidget(0,5)
        self.table.setObjectName('resultsTable')
        self.table.horizontalHeader().setStyleSheet(
            'QHeaderView::section { background-color: #293845; color: #f5f9fc; padding: 5px; border: 1px solid #465966; }')
        self.table.setHorizontalHeaderLabels(['Plugin','Installed','Target status','Target release','Review notes'])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        for col in range(4):
            self.table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._details)
        layout.addWidget(self.table,1)
        self.details = QTextBrowser()
        self.details.setObjectName('reviewDetails')
        self.details.setOpenExternalLinks(False)
        self.details.setMaximumHeight(155)
        self.details.anchorClicked.connect(self._open_source)
        self.details.setPlainText('Select a result to read the full review notes.')
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.copy = QPushButton('Copy report')
        self.copy.clicked.connect(self._copy)
        self.export = QPushButton('Save report…')
        self.export.setObjectName('saveReport')
        self.export.clicked.connect(self._save)
        self.copy.setEnabled(False)
        self.export.setEnabled(False)
        actions.addWidget(self.copy)
        actions.addWidget(self.export)
        actions.addStretch()
        close = QPushButton('Close')
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        self.target.currentTextChanged.connect(self._invalidate)

    def _invalidate(self):
        if self.busy:
            return
        self.report = None
        self.table.setRowCount(0)
        self.copy.setEnabled(False)
        self.export.setEnabled(False)
        self.details.setPlainText('Select a result to read the full review notes.')
        self._message('Choose a target and check this profile. Changing the target clears the previous report.')

    def _message(self, text):
        self.message.setText(text)

    def _set_busy(self, busy):
        self.busy = busy
        self.target.setEnabled(not busy)
        self.check.setEnabled(not busy)
        self.cancel.setVisible(busy)
        self.progress.setVisible(busy)

    def start(self):
        self._invalidate()
        try:
            self.selected_target = target_version(self.target.currentText())
            self.current = current_version()
            self.installed = installed_plugins()
        except Exception as error:
            self._failed(str(error))
            return
        if not self.installed:
            self._message('No Python plugin metadata or saved references were found in this profile.')
            return
        self._set_busy(True)
        self.fetcher.start(self.current,self.selected_target)

    def _failed(self, message):
        self._set_busy(False)
        self.report = None
        self.table.setRowCount(0)
        self.details.setPlainText('No new report was produced.')
        self.copy.setEnabled(False)
        self.export.setEnabled(False)
        self._message(message)

    def _complete(self, indexes, timestamp):
        try:
            rows = compare(self.installed,indexes[index_url(self.current)],
                           indexes[index_url(self.selected_target)],self.selected_target)
            self.report = make_report(rows,self.current,self.selected_target,timestamp)
            self.table.setRowCount(len(rows))
            for i,row in enumerate(rows):
                values = [row.name,row.installed or 'Unknown',STATUSES[row.status],row.target_release or '—',' '.join(row.notes)]
                for j,text in enumerate(values):
                    cell = QTableWidgetItem(text)
                    cell.setToolTip(text)
                    if j == 0: cell.setData(Qt.UserRole,i)
                    if row.status in ('EXPERIMENTAL','DEPRECATED','UNVERIFIED','NO_RELEASE'):
                        cell.setBackground(QColor('#fff2d5'))
                        cell.setForeground(QColor('#352910'))
                    self.table.setItem(i,j,cell)
            listed = sum(r.status == 'DECLARED' for r in rows)
            self._message(f'{len(rows)} entries · {listed} with a non-deprecated stable target release · target {self.selected_target} · fetched {timestamp[:19]} UTC. Review the remaining entries individually.')
            self.copy.setEnabled(True)
            self.export.setEnabled(True)
            if rows: self.table.selectRow(0)
        except Exception as error:
            self._failed('Report could not be completed: '+str(error))
        finally:
            self._set_busy(False)

    def _details(self):
        from html import escape
        if not self.report or self.table.currentRow() < 0:
            return
        row = self.report['rows'][self.table.currentRow()]
        content = '<b>'+escape(row['name'])+'</b><ul>'+''.join('<li>'+escape(n)+'</li>' for n in row['notes'])+'</ul>'
        if row['source']:
            content += '<a href="'+escape(row['source'],quote=True)+'">Read the author’s official page</a>'
        self.details.setHtml(content)

    def _open_source(self, url):
        if url.scheme() == 'https' and url.host() == 'plugins.qgis.org':
            QDesktopServices.openUrl(url)

    def _copy(self):
        if self.report:
            QApplication.clipboard().setText(plain_report(self.report))
            self._message('Report copied. It may contain private plugin names; review before sharing.')

    def _save(self):
        if not self.report:
            return
        path, selected = QFileDialog.getSaveFileName(self,'Save Upgrade Check report',
                        str(Path(self.last_export_dir)/f"upgrade-check-{self.report['target_qgis']}.html"),
                        'HTML report (*.html);;JSON data (*.json)')
        if not path:
            return
        is_json = selected.startswith('JSON')
        suffix = '.json' if is_json else '.html'
        if not path.lower().endswith(suffix):
            path += suffix
            if Path(path).exists() and QMessageBox.question(
                    self,'Replace existing report?',f'{Path(path).name} already exists. Replace it?',
                    QMessageBox.Yes | QMessageBox.No,QMessageBox.No) != QMessageBox.Yes:
                return
        try:
            from qgis.PyQt.QtCore import QIODevice, QSaveFile
            destination = QSaveFile(path)
            payload = (json_report(self.report) if is_json else html_report(self.report)).encode('utf-8')
            if not destination.open(QIODevice.WriteOnly):
                raise OSError(destination.errorString())
            if destination.write(payload) != len(payload):
                destination.cancelWriting()
                raise OSError(destination.errorString())
            if not destination.commit():
                raise OSError(destination.errorString())
            self.last_export_dir = str(Path(path).parent)
            self._message('Report saved. Files stay on this device; review plugin names before sharing.')
        except OSError as error:
            QMessageBox.warning(self,'Could not save report',str(error))

    def reject(self):
        self.fetcher.cancel()
        super().reject()


class UpgradeCheck:
    def __init__(self, iface):
        self.iface = iface
        self.dialog = None

    def initGui(self):
        icon = QIcon(str(Path(__file__).with_name('icon.svg')))
        self.action = QAction(icon,'Upgrade Check…',self.iface.mainWindow())
        self.action.setObjectName('upgradeCheckAction')
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu('Upgrade Check',self.action)
        self.iface.addToolBarIcon(self.action)

    def run(self):
        if self.dialog is None:
            self.dialog = CheckDialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def unload(self):
        if self.dialog is not None:
            self.dialog.reject()
            self.dialog.deleteLater()
            self.dialog = None
        self.iface.removePluginMenu('Upgrade Check',self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action.deleteLater()
