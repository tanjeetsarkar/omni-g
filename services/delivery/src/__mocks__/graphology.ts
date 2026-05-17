// Stub Graphology for jsdom tests.
const Graph = jest.fn().mockImplementation(() => ({
  addNode: jest.fn(),
  addEdgeWithKey: jest.fn(),
  hasNode: jest.fn().mockReturnValue(true),
  forEachNode: jest.fn(),
  getNodeAttribute: jest.fn().mockReturnValue("#6366f1"),
  setNodeAttribute: jest.fn(),
  order: 0,
}));

export default Graph;
