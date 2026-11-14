#include "AssetProvider.h"
#include <QColor>
#include <QDir>
#include <QFileInfo>
#include <algorithm>

QImage AssetProvider::tint(const QImage& source, QColor colour, qreal opacity)
{
    QImage result(source.size(), QImage::Format_ARGB32_Premultiplied);
    for (int y = 0; y < source.height(); ++y)
    {
        auto* row = reinterpret_cast<QRgb*>(result.scanLine(y));
        for (int x = 0; x < source.width(); ++x)
        {
            const auto pixel = source.pixel(x, y);
            const int alpha =
                qBound(0, qRound(qGray(pixel) * (qAlpha(pixel) / 255.0) * opacity), 255);
            row[x] = qPremultiply(qRgba(colour.red(), colour.green(), colour.blue(), alpha));
        }
    }
    return result;
}

QRect AssetProvider::goldFrameBounds(const QImage& image)
{
    int left = image.width(), top = image.height(), right = -1, bottom = -1;
    for (int y = 0; y < image.height(); ++y)
    {
        for (int x = 0; x < image.width(); ++x)
        {
            const auto p = image.pixelColor(x, y);
            if (p.alpha() > 150 && p.red() > 175 && p.green() > 140 && p.green() - p.blue() > 25)
            {
                left = qMin(left, x);
                top = qMin(top, y);
                right = qMax(right, x);
                bottom = qMax(bottom, y);
            }
        }
    }
    return right >= left ? QRect(QPoint(left, top), QPoint(right, bottom)) : image.rect();
}

bool AssetProvider::load(const QString& directory)
{
    QHash<QString, QImage> images;
    QDir folder(directory);
    const auto read = [&](const QString& name, const QString& extension = ".png")
    {
        if (images.contains(name))
        {
            return images.value(name);
        }
        const QImage image(folder.filePath(name + extension));
        if (!image.isNull())
        {
            images.insert(name, image);
        }
        return image;
    };
    if (read("chronicle-header").isNull() || read("chronicle-tapestry", ".jpg").isNull())
    {
        return false;
    }
    auto tapestry = images.value("chronicle-tapestry");
    images.insert("chronicle-tapestry",
                  tapestry.copy(35, 45, tapestry.width() - 70, tapestry.height() - 90));
    auto header = images.value("chronicle-header").convertToFormat(QImage::Format_ARGB32);
    QRect bounds;
    for (int y = 0; y < header.height(); ++y)
    {
        for (int x = 0; x < header.width(); ++x)
        {
            if (qAlpha(header.pixel(x, y)) > 0)
            {
                bounds |= QRect(x, y, 1, 1);
            }
        }
    }
    header = header.copy(bounds);
    images.insert("header", header);
    images.remove("chronicle-header");
    auto gold = header;
    for (int y = 0; y < gold.height(); ++y)
    {
        for (int x = 0; x < gold.width(); ++x)
        {
            auto c = gold.pixelColor(x, y);
            const qreal light = qGray(c.rgb()) / 255.0;
            gold.setPixelColor(x, y,
                               QColor::fromRgbF(.44 + .36 * light, .30 + .30 * light,
                                                .10 + .13 * light, c.alphaF()));
        }
    }
    images.insert("header-gold", gold);

    const struct
    {
        const char* name;
        const char* source;
        const char* colour;
        qreal opacity;
    } masks[] = {{"row", "row-mask", "#7b653b", .3},
                 {"row-hover", "row-mask", "#9a814a", .45},
                 {"row-selected", "row-mask", "#3b5f9b", .9},
                 {"row-ornament", "row-ornament", "#a57d48", .85},
                 {"row-ornament-blue", "row-ornament", "#8aaadd", .9},
                 {"frame", "description-corner", "#bb8a56", 1},
                 {"scroll-rail", "scroll-rail", "#99733e", .7},
                 {"scroll-thumb", "scroll-thumb", "#dca549", .95}};

    for (const auto& mask : masks)
    {
        const auto source = read(QString("chronicle-") + mask.source);
        if (!source.isNull())
        {
            auto image = tint(source, QColor(mask.colour), mask.opacity);
            if (QString(mask.name) == "frame")
            {
                image = image.scaled(323, 79, Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
            }
            images.insert(mask.name, image);
        }
    }
    const auto ornament = read("ornament");
    if (!ornament.isNull())
    {
        images.insert("title-ornament", tint(ornament, QColor("#b7a44c")));
    }
    // The gold trim, rather than the surrounding parchment/halo, defines the hit rectangle.
    const QRect buttonBounds = goldFrameBounds(read("button"));
    for (const auto& name : {"button", "button-disabled"})
    {
        auto image = read(name).copy(buttonBounds).convertToFormat(QImage::Format_ARGB32);
        for (int y = 0; y < image.height(); ++y)
        {
            for (int x = 0; x < image.width(); ++x)
            {
                auto c = image.pixelColor(x, y);
                c.setRed(qRound(c.red() * .88));
                c.setGreen(qRound(c.green() * .88));
                c.setBlue(qRound(c.blue() * .88));
                image.setPixelColor(x, y, c);
            }
        }
        images.insert(QString("face-") + name, image);
        images.remove(name);
    }
    QWriteLocker guard(&m_lock);
    m_images = std::move(images);
    m_directory = directory;
    return true;
}

QImage AssetProvider::requestImage(const QString& id, QSize* size, const QSize&)
{
    QReadLocker guard(&m_lock);
    const auto image = m_images.value(id.section('?', 0, 0));
    if (size)
    {
        *size = image.size();
    }
    return image;
}
