/**
 * Stub for dagre — used in jsdom test environment.
 */
const mockGraph = {
  setDefaultEdgeLabel: jest.fn(),
  setGraph: jest.fn(),
  setNode: jest.fn(),
  setEdge: jest.fn(),
  node: jest.fn().mockReturnValue({ x: 50, y: 50 }),
};

const dagre = {
  graphlib: {
    Graph: jest.fn().mockImplementation(() => mockGraph),
  },
  layout: jest.fn(),
};

export default dagre;
module.exports = dagre;
