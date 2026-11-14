#include "BackendClient.h"
#include <QDateTime>
#include <QDir>
#include <QJsonDocument>
#include <QUuid>
#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#endif

BackendClient::BackendClient(QString python, QString bridge, QString core, QString data,
                             QObject* parent)
    : QObject(parent), m_python(std::move(python)), m_bridge(std::move(bridge)),
      m_core(std::move(core)), m_data(std::move(data))
{
    m_process.setProcessChannelMode(QProcess::MergedChannels);
#ifdef Q_OS_WIN
    m_process.setCreateProcessArgumentsModifier(
        [](QProcess::CreateProcessArguments* args)
        {
            args->flags |= CREATE_NO_WINDOW;
        });
#endif
    connect(&m_process, &QProcess::started, this, &BackendClient::attachJob);
    connect(&m_process, &QProcess::readyReadStandardOutput, this,
            [this]
            {
                feed(m_process.readAllStandardOutput());
            });
    connect(&m_process, &QProcess::finished, this,
            [this](int code, QProcess::ExitStatus)
            {
                feed(m_process.readAllStandardOutput());
                if (!m_buffer.isEmpty())
                {
                    feed("\n");
                }
                m_log.close();
                closeJob();
                emit finished(code, m_cancelled);
            });
    connect(&m_process, &QProcess::errorOccurred, this,
            [this](QProcess::ProcessError error)
            {
                if (error == QProcess::FailedToStart)
                {
                    emit eventReceived({{"type", "error"}, {"message", m_process.errorString()}});
                    m_log.close();
                    closeJob();
                    emit finished(-1, false);
                }
            });
}

BackendClient::~BackendClient()
{
    if (running())
    {
        cancel();
        m_process.waitForFinished(3000);
    }
    closeJob();
}

bool BackendClient::start(const QJsonObject& request)
{
    if (running())
    {
        return false;
    }
    m_cancelled = false;
    m_buffer.clear();
    QDir().mkpath(m_data + "/logs");
    m_log.setFileName(m_data + "/logs/" +
                      QDateTime::currentDateTimeUtc().toString("yyyyMMdd-HHmmss-zzz") + "-" +
                      QUuid::createUuid().toString(QUuid::WithoutBraces).left(8) + ".log");
    m_log.open(QIODevice::WriteOnly | QIODevice::Truncate);
    auto environment = QProcessEnvironment::systemEnvironment();
    environment.insert("PYTHONUTF8", "1");
    environment.insert("PYTHONUNBUFFERED", "1");
    environment.insert("PYTHONDONTWRITEBYTECODE", "1");
    m_process.setProcessEnvironment(environment);
    m_process.setWorkingDirectory(m_core);
    m_process.start(m_python,
                    {"-B", "-u", "-X", "utf8", m_bridge, "--core", m_core, "--data", m_data});
    auto envelope = request;
    envelope["protocol"] = 1;
    m_process.write(QJsonDocument(envelope).toJson(QJsonDocument::Compact));
    m_process.closeWriteChannel();
    return true;
}

void BackendClient::feed(const QByteArray& bytes)
{
    m_buffer += bytes;
    constexpr qsizetype maximumLine = 4 * 1024 * 1024;
    const auto rejectOversizedLine = [this]
    {
        emit eventReceived(
            {{"type", "error"}, {"message", tr("Réponse du moteur trop volumineuse")}});
        m_buffer.clear();
        cancel();
    };
    // Consume the batch with a cursor; compact the pending fragment only once.
    // Removing the prefix for every log line repeatedly moved the same bytes.
    qsizetype start = 0;
    qsizetype end;
    while ((end = m_buffer.indexOf('\n', start)) >= 0)
    {
        if (end - start > maximumLine)
        {
            rejectOversizedLine();
            return;
        }
        const auto line = m_buffer.mid(start, end - start).trimmed();
        start = end + 1;
        if (line.isEmpty())
        {
            continue;
        }
        if (m_log.isOpen())
        {
            m_log.write(line);
            m_log.write("\n");
        }
        if (line.startsWith("HMBGUI "))
        {
            QJsonParseError error;
            const auto document = QJsonDocument::fromJson(line.mid(7), &error);
            if (error.error == QJsonParseError::NoError && document.isObject())
            {
                emit eventReceived(document.object());
                continue;
            }
        }
        emit eventReceived({{"type", "log"}, {"text", QString::fromUtf8(line)}});
    }
    m_buffer.remove(0, start);
    if (m_buffer.size() > maximumLine)
    {
        rejectOversizedLine();
    }
}

void BackendClient::attachJob()
{
#ifdef Q_OS_WIN
    m_job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION info{};
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    HANDLE process =
        OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, FALSE, DWORD(m_process.processId()));
    const bool attached =
        m_job && process &&
        SetInformationJobObject(m_job, JobObjectExtendedLimitInformation, &info, sizeof(info)) &&
        AssignProcessToJobObject(m_job, process);
    if (process)
    {
        CloseHandle(process);
    }
    if (!attached)
    {
        emit eventReceived(
            {{"type", "error"},
             {"message", tr("Impossible d’isoler le processus moteur ; opération arrêtée.")}});
        closeJob();
        m_process.kill();
    }
#endif
}

void BackendClient::closeJob()
{
#ifdef Q_OS_WIN
    if (m_job)
    {
        CloseHandle(HANDLE(m_job));
        m_job = nullptr;
    }
#endif
}

void BackendClient::cancel()
{
    m_cancelled = true;
#ifdef Q_OS_WIN
    if (m_job)
    {
        TerminateJobObject(HANDLE(m_job), 130);
    }
#endif
    m_process.kill();
}
