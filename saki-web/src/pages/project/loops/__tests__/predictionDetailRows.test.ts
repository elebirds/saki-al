import type {PredictionItemRead} from '../../../../types';
import {expandPredictionDetailItems} from '../predictionDetailRows';

const items: PredictionItemRead[] = [
    {
        sampleId: 'sample-a',
        rank: 1,
        score: 0.91,
        labelId: 'label-primary',
        geometry: {rect: {x: 1, y: 2, width: 3, height: 4}},
        attrs: {},
        confidence: 0.91,
        meta: {
            base_predictions: [
                {
                    class_index: 3,
                    class_name: 'car',
                    confidence: 0.82,
                    geometry: {
                        obb: {
                            cx: 10,
                            cy: 20,
                            width: 30,
                            height: 12,
                            angle_deg_ccw: 15,
                        },
                    },
                },
                {
                    class_index: 4,
                    class_name: 'bus',
                    confidence: 0.78,
                    geometry: {
                        rect: {
                            x: 5,
                            y: 6,
                            width: 7,
                            height: 8,
                        },
                    },
                },
            ],
        },
    },
    {
        sampleId: 'sample-b',
        rank: 2,
        score: 0.37,
        labelId: 'label-fallback',
        geometry: {rect: {x: 9, y: 9, width: 2, height: 2}},
        attrs: {},
        confidence: 0.37,
        meta: {},
    },
];

const rows = expandPredictionDetailItems(items);

if (rows.length !== 3) {
    throw new Error(`expected 3 rows, got ${rows.length}`);
}

if (rows[0]?.sampleId !== 'sample-a' || rows[0]?.boxIndex !== 1 || rows[0]?.geometryType !== 'obb') {
    throw new Error(`unexpected first expanded row: ${JSON.stringify(rows[0])}`);
}

if (rows[0]?.className !== 'car' || rows[0]?.classIndex !== 3) {
    throw new Error(`unexpected first class payload: ${JSON.stringify(rows[0])}`);
}

if (rows[1]?.sampleId !== 'sample-a' || rows[1]?.boxIndex !== 2 || rows[1]?.geometryType !== 'rect') {
    throw new Error(`unexpected second expanded row: ${JSON.stringify(rows[1])}`);
}

if (rows[2]?.sampleId !== 'sample-b' || rows[2]?.boxIndex !== 1 || rows[2]?.geometryType !== 'rect') {
    throw new Error(`unexpected fallback row: ${JSON.stringify(rows[2])}`);
}
