const ExamRegistry = artifacts.require("ExamRegistry");

module.exports = function (deployer) {
  deployer.deploy(ExamRegistry);
};
