// Stub Graphology for jsdom tests.
const Graph = jest.fn().mockImplementation(() => ({
  addNode: jest.fn(),
  addEdgeWithKey: jest.fn(),
  hasNode: jest.fn().mockReturnValue(true),
}));

export default Graph;
